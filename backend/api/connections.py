"""v4.0 Phase C — /settings/connections API.

Meta OAuth flow:
    1. GET  /connections/meta/oauth-url        → returns Facebook login URL
    2. Browser redirects to Facebook, back to /connections/meta/callback?code=...
    3. GET  /connections/meta/callback         → exchanges code, stores encrypted token,
       lists ad accounts + pages + IG accounts
    4. POST /connections/meta/select           → tenant picks {ad_account_id, page_id, ig_user_id}

    GET  /connections                          → list of tenant's connections (status view)
    POST /connections/{id}/refresh              → re-verify token, refresh ad-account/page cache
    DEL  /connections/{id}                      → mark disconnected + zero out selection
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, current_user
from config import settings
from db.session import tenant_connection
from token_crypto import encrypt

router = APIRouter(prefix="/connections", tags=["connections"])
log = logging.getLogger("connections_api")


# The permissions we actually use across meta_ads + instagram_organic + watcher.
# Approval scope for App Review filings — see docs/meta-approval-filings.md.
_META_SCOPES = [
    "ads_management",
    "ads_read",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_read_user_content",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "business_management",
    "email",
]


class ConnectionOut(BaseModel):
    id: UUID
    provider: str = "meta"
    meta_user_id: str
    meta_user_name: str | None
    status: str
    brand_id: UUID | None = None       # scoped to this brand; null = tenant default
    selected_ad_account_id: str | None
    selected_page_id: str | None
    selected_page_name: str | None
    selected_ig_user_id: str | None
    selected_ig_username: str | None
    token_expires_at: str | None
    last_verified_at: str | None
    last_error: str | None


def _row(r: tuple) -> ConnectionOut:
    return ConnectionOut(
        id=r[0], meta_user_id=r[1], meta_user_name=r[2],
        status=r[3],
        selected_ad_account_id=r[4], selected_page_id=r[5],
        selected_page_name=r[6], selected_ig_user_id=r[7],
        selected_ig_username=r[8],
        token_expires_at=r[9].isoformat() if r[9] else None,
        last_verified_at=r[10].isoformat() if r[10] else None,
        last_error=r[11],
        brand_id=r[12],
    )


_SELECT = ("id, meta_user_id, meta_user_name, status, selected_ad_account_id, "
           "selected_page_id, selected_page_name, selected_ig_user_id, "
           "selected_ig_username, token_expires_at, last_verified_at, last_error, brand_id")


# ============================================================
# OAuth kickoff
# ============================================================

@router.get("/meta/oauth-url")
def get_oauth_url(
    brand_id: UUID | None = Query(None),
    user: CurrentUser = Depends(current_user),
):
    """Returns a Facebook Login URL. The tenant + (optional) brand are bound
    into the `state` token so the callback knows which brand to attach the
    resulting connection to."""
    if not (settings.meta_app_id and settings.meta_app_secret and settings.meta_redirect_uri):
        raise HTTPException(503, "Meta integration not configured — set META_APP_ID, "
                                 "META_APP_SECRET, META_REDIRECT_URI on the API service")
    from meta_client import build_oauth_url

    state_token = secrets.token_urlsafe(24)
    # Persist a one-shot state row w/ the intended brand for this connection.
    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'meta.oauth.state', 'meta_connection', %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), state_token,
             json.dumps({"expires_in": 600,
                         "brand_id": str(brand_id) if brand_id else None})),
        )
    return {"url": build_oauth_url(state_token, _META_SCOPES), "state": state_token}


@router.get("/meta/callback")
def oauth_callback(code: str = Query(...), state: str = Query(...),
                   user: CurrentUser = Depends(current_user)):
    """Exchange code → user token → long-lived token → save encrypted."""
    from meta_client import (exchange_code, exchange_long_lived, get_me,
                             list_ad_accounts, list_pages,
                             get_ig_business_account, MetaAPIError)

    # Verify state — recent, matching tenant. Also pluck the target brand_id
    # that /oauth-url stashed on the state row.
    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "SELECT id, meta FROM audit_log WHERE tenant_id = %s AND action = 'meta.oauth.state' "
            "AND entity_id = %s AND created_at > now() - interval '15 minutes' "
            "ORDER BY created_at DESC LIMIT 1",
            (str(user.tenant_id), state),
        ).fetchone()
    if not r:
        raise HTTPException(400, "invalid or expired OAuth state")
    brand_id_for_conn = ((r[1] or {}).get("brand_id")) if isinstance(r[1], dict) else None

    try:
        short = exchange_code(code)
        long_lived = exchange_long_lived(short["access_token"])
        user_token = long_lived["access_token"]
        expires_in = int(long_lived.get("expires_in") or 0)
        me = get_me(user_token)
    except MetaAPIError as e:
        log.warning("meta OAuth exchange failed: %s", e)
        raise HTTPException(400, f"Meta OAuth: {e}")

    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None

    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "INSERT INTO meta_connections (tenant_id, brand_id, meta_user_id, meta_user_name, "
            "encrypted_access_token, token_scopes, token_expires_at, status, last_verified_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'connected', now()) "
            "ON CONFLICT (tenant_id, meta_user_id) DO UPDATE SET "
            "brand_id = EXCLUDED.brand_id, "
            "encrypted_access_token = EXCLUDED.encrypted_access_token, "
            "token_scopes = EXCLUDED.token_scopes, "
            "token_expires_at = EXCLUDED.token_expires_at, "
            "status = 'connected', last_verified_at = now(), last_error = NULL, "
            "meta_user_name = EXCLUDED.meta_user_name, updated_at = now()",
            (str(user.tenant_id), brand_id_for_conn, me["id"], me.get("name"),
             encrypt(user_token), _META_SCOPES, expires_at),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, 'meta.oauth.connected', 'meta_connection', %s)",
            (str(user.tenant_id), str(user.user_id), me["id"]),
        )

    # Load ad accounts + pages + IG accounts so the picker UI can render.
    return {
        "ok": True,
        "meta_user": me,
        "ad_accounts": _safe(list_ad_accounts, user_token),
        "pages": _pages_with_ig(user_token),
    }


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log.warning("meta list failed: %s", e)
        return []


def _pages_with_ig(user_token: str) -> list[dict[str, Any]]:
    from meta_client import list_pages, get_ig_business_account
    pages = _safe(list_pages, user_token)
    out = []
    for p in pages:
        ig = None
        try:
            ig = get_ig_business_account(p["id"], p.get("access_token") or user_token)
        except Exception:
            pass
        entry = {"id": p["id"], "name": p.get("name"),
                 "page_access_token": p.get("access_token")}
        if ig:
            entry["ig"] = {"id": ig["id"], "username": ig.get("username")}
        out.append(entry)
    return out


# ============================================================
# Select ad account / page / IG (post-callback picker)
# ============================================================

class SelectIn(BaseModel):
    connection_id: UUID
    ad_account_id: str | None = None
    page_id: str | None = None
    page_access_token: str | None = None
    page_name: str | None = None
    ig_user_id: str | None = None
    ig_username: str | None = None


@router.post("/meta/select")
def select_targets(payload: SelectIn, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "SELECT id FROM meta_connections WHERE id = %s AND tenant_id = %s",
            (str(payload.connection_id), str(user.tenant_id)),
        ).fetchone()
        if not r:
            raise HTTPException(404, "connection not found")
        conn.execute(
            "UPDATE meta_connections SET "
            "selected_ad_account_id = %s, "
            "selected_page_id = %s, selected_page_name = %s, "
            "selected_page_access_token = %s, "
            "selected_ig_user_id = %s, selected_ig_username = %s, "
            "updated_at = now() WHERE id = %s",
            (payload.ad_account_id,
             payload.page_id, payload.page_name,
             encrypt(payload.page_access_token) if payload.page_access_token else None,
             payload.ig_user_id, payload.ig_username,
             str(payload.connection_id)),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'meta.select', 'meta_connection', %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), str(payload.connection_id),
             json.dumps({
                 "ad_account": payload.ad_account_id or "",
                 "page_id": payload.page_id or "",
                 "ig_user_id": payload.ig_user_id or "",
             })),
        )
    return {"ok": True}


# ============================================================
# List / refresh / disconnect
# ============================================================

@router.get("", response_model=list[ConnectionOut])
def list_connections(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            f"SELECT {_SELECT} FROM meta_connections WHERE tenant_id = %s "
            "ORDER BY updated_at DESC",
            (str(user.tenant_id),),
        ).fetchall()
    return [_row(r) for r in rows]


@router.post("/{connection_id}/refresh")
def refresh(connection_id: UUID, user: CurrentUser = Depends(current_user)):
    """Re-verify the stored token and refresh the ad-account/page listing."""
    from meta_client import get_me, MetaAPIError
    from token_crypto import decrypt as _dec
    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "SELECT encrypted_access_token FROM meta_connections "
            "WHERE id = %s AND tenant_id = %s",
            (str(connection_id), str(user.tenant_id)),
        ).fetchone()
        if not r:
            raise HTTPException(404, "connection not found")
        try:
            token = _dec(r[0])
            get_me(token)
            conn.execute(
                "UPDATE meta_connections SET last_verified_at = now(), "
                "status = 'connected', last_error = NULL, updated_at = now() "
                "WHERE id = %s",
                (str(connection_id),),
            )
            return {"ok": True,
                    "ad_accounts": _safe(__import__('meta_client').list_ad_accounts, token),
                    "pages": _pages_with_ig(token)}
        except (MetaAPIError, Exception) as e:
            conn.execute(
                "UPDATE meta_connections SET status = 'error', last_error = %s, "
                "updated_at = now() WHERE id = %s",
                (str(e)[:500], str(connection_id)),
            )
            raise HTTPException(400, f"connection unusable: {e}")


@router.delete("/{connection_id}")
def disconnect(connection_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE meta_connections SET status = 'disconnected', updated_at = now() "
            "WHERE id = %s AND tenant_id = %s",
            (str(connection_id), str(user.tenant_id)),
        ).rowcount
        if n:
            conn.execute(
                "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
                "values (%s, %s, 'meta.disconnect', 'meta_connection', %s)",
                (str(user.tenant_id), str(user.user_id), str(connection_id)),
            )
    if not n:
        raise HTTPException(404, "connection not found")
    return {"ok": True}
