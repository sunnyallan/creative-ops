"""Thin client for the self-hosted Penpot instance.

We deliberately depend on only two surfaces:
  1. RPC get-file  — to resolve a board (frame) id from its name
  2. /api/export   — the exporter's frame → SVG rendering

Both are authenticated with a personal access token. Penpot's RPC speaks
transit+json by default but honours Accept: application/json; keys arrive
kebab-cased (e.g. "pages-index") and occasionally tilde-prefixed ("~:objects")
depending on version, so parsing below is defensive. Pin the Penpot image
version in Railway to keep this stable.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from config import settings


class PenpotError(RuntimeError):
    pass


def _base() -> str:
    base = (settings.penpot_base_url or "").rstrip("/")
    if not base:
        raise PenpotError("PENPOT_BASE_URL is not configured")
    return base


def _headers() -> dict[str, str]:
    token = settings.penpot_access_token
    if not token:
        raise PenpotError("PENPOT_ACCESS_TOKEN is not configured")
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _norm_key(k: Any) -> str:
    """Normalise transit-ish keys: '~:pages-index' → 'pages-index'."""
    s = str(k)
    return s[2:] if s.startswith("~:") else s


def _norm(obj: Any) -> Any:
    """Recursively normalise a decoded Penpot RPC payload."""
    if isinstance(obj, dict):
        return {_norm_key(k): _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("~u"):  # transit uuid literal
        return obj[2:]
    return obj


def get_file(file_id: str) -> dict:
    resp = httpx.post(
        f"{_base()}/api/rpc/command/get-file",
        headers=_headers(),
        json={"id": file_id},
        timeout=60,
    )
    if resp.status_code != 200:
        raise PenpotError(f"get-file failed ({resp.status_code}): {resp.text[:300]}")
    return _norm(resp.json())


def find_frame(file_data: dict, page_id: str | None, board_name: str) -> tuple[str, str, dict]:
    """Locate a frame by name. Returns (page_id, frame_id, frame_object).
    If page_id is None, searches every page."""
    data = file_data.get("data") or file_data
    pages_index = data.get("pages-index") or data.get("pagesIndex") or {}
    if not pages_index:
        raise PenpotError("file data has no pages-index — Penpot version mismatch?")

    wanted = board_name.strip().lower()
    for pid, page in pages_index.items():
        if page_id and str(pid) != str(page_id):
            continue
        objects = (page or {}).get("objects") or {}
        for oid, obj in objects.items():
            if not isinstance(obj, dict):
                continue
            otype = str(obj.get("type", ""))
            if otype.endswith("frame") and str(obj.get("name", "")).strip().lower() == wanted:
                return str(pid), str(oid), obj
    raise PenpotError(
        f"board '{board_name}' not found"
        + (f" on page {page_id}" if page_id else " on any page")
        + " — check the board name matches exactly."
    )


def export_frame_svg(file_id: str, page_id: str, frame_id: str) -> bytes:
    """Render one frame to SVG via the exporter (proxied through the frontend)."""
    payload = {
        "wait": True,
        "exports": [{
            "type": "svg",
            "file-id": file_id,
            "page-id": page_id,
            "object-id": frame_id,
            "scale": 1,
            "suffix": "",
        }],
    }
    resp = httpx.post(f"{_base()}/api/export", headers=_headers(), json=payload, timeout=120)
    if resp.status_code != 200:
        raise PenpotError(f"export failed ({resp.status_code}): {resp.text[:300]}")

    ctype = resp.headers.get("content-type", "")
    body = resp.content
    # Direct SVG back
    if b"<svg" in body[:2000] or "svg" in ctype:
        return body
    # JSON envelope with a download uri
    try:
        info = resp.json()
        uri = info.get("uri") or (info.get("data") or {}).get("uri")
        if uri:
            dl = httpx.get(
                uri if uri.startswith("http") else f"{_base()}{uri}",
                headers={"Authorization": _headers()["Authorization"]},
                timeout=120,
            )
            if dl.status_code == 200 and b"<svg" in dl.content[:2000]:
                return dl.content
            raise PenpotError(f"export download failed ({dl.status_code})")
    except json.JSONDecodeError:
        pass
    raise PenpotError(f"export returned unexpected payload (content-type {ctype})")
