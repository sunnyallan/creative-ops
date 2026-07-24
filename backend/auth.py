"""Auth: validate Supabase JWTs by asking Supabase, not by decoding locally.

This works with both legacy HS256 and the newer asymmetric (ES256/RS256) keys
that Supabase issues on new projects, because we just forward the token to
Supabase's /auth/v1/user endpoint and trust its answer.

Trade-off: one HTTP call per request (cached briefly in-process). Fine for MVP.
"""
from __future__ import annotations

import time
from uuid import UUID

import httpx
from fastapi import Header, HTTPException, status

from config import settings


class CurrentUser:
    def __init__(self, user_id: UUID, email: str, tenant_id: UUID):
        self.user_id = user_id
        self.email = email
        self.tenant_id = tenant_id


# Tiny in-process cache so we don't hit Supabase on every request.
_TOKEN_CACHE: dict[str, tuple[float, dict]] = {}
_TOKEN_TTL = 60  # seconds


def _verify_with_supabase(token: str) -> dict:
    now = time.time()
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]

    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "supabase not configured")

    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_anon_key,
    }
    try:
        r = httpx.get(url, headers=headers, timeout=10)
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"supabase unreachable: {e}")

    if r.status_code != 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {r.text}")

    user = r.json()
    _TOKEN_CACHE[token] = (now + _TOKEN_TTL, user)
    return user


def _ensure_tenant(user_id: UUID, email: str) -> UUID:
    """One tenant per user for MVP. Create on first call."""
    import psycopg
    with psycopg.connect(settings.supabase_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE owner_user_id = %s LIMIT 1", (str(user_id),))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO tenants (name, owner_user_id) VALUES (%s, %s) RETURNING id",
                (email.split("@")[0] if email else "tenant", str(user_id)),
            )
            tenant_id = cur.fetchone()[0]
            conn.commit()
            return tenant_id


def _allowed_email(email: str) -> bool:
    """Check the ALLOWED_EMAILS allowlist. Empty allowlist = allow all
    (dev-friendly default). Otherwise a case-insensitive exact match."""
    raw = (settings.allowed_emails or "").strip()
    if not raw:
        return True
    allowed = {e.strip().lower() for e in raw.split(",") if e.strip()}
    return (email or "").strip().lower() in allowed


def current_user(authorization: str = Header(...)) -> CurrentUser:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    user = _verify_with_supabase(token)
    user_id = UUID(user["id"])
    email = user.get("email", "") or ""
    if not _allowed_email(email):
        # 403 (not 401) — token IS valid, this user is just not permitted.
        # The frontend can differentiate: 401 → show login, 403 → show
        # "you're signed in but this workspace isn't open to your email".
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"account {email or 'unknown'} is not permitted on this workspace",
        )
    tenant_id = _ensure_tenant(user_id, email)
    return CurrentUser(user_id=user_id, email=email, tenant_id=tenant_id)
