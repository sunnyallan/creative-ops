"""v3.0 custom templates — designed in self-hosted Penpot, synced as SVG.

Registration flow:
  1. Designer builds a board in Penpot with placeholder layer names
     (#headline, #body, #cta, #image, #logo, #partner_logo, #slide_pip)
  2. POST /templates with the pasted Penpot workspace URL + the board name
  3. template_sync worker exports the board as SVG, parses placeholder zones,
     renders a dummy-content preview → sync_status becomes 'synced'
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, current_user
from config import settings
from db.session import tenant_connection
from storage import signed_url

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/penpot-info")
def penpot_info(user: CurrentUser = Depends(current_user)):
    """Where the self-hosted Penpot lives + whether the platform can reach it.
    Lets the frontend show 'Open in Penpot' links without a separate NEXT_PUBLIC var."""
    base = (settings.penpot_base_url or "").rstrip("/")
    return {
        "base_url": base,
        "configured": bool(base and settings.penpot_access_token),
    }


class TemplateIn(BaseModel):
    name: str
    penpot_url: str          # pasted workspace URL containing file-id (+ page-id)
    board_name: str          # the frame/board name inside Penpot, e.g. "IG Post v1"


class TemplateOut(BaseModel):
    id: UUID
    name: str
    penpot_file_id: str | None
    penpot_page_id: str | None
    penpot_frame_id: str | None
    board_name: str | None = None
    sync_status: str
    sync_error: str | None
    preview_url: str | None
    zones: dict | None
    last_synced_at: str | None


def _parse_penpot_url(url: str) -> tuple[str | None, str | None]:
    """Extract file-id and page-id from a pasted Penpot workspace URL.
    Penpot puts them in the fragment query: /#/workspace?team-id=..&file-id=..&page-id=.."""
    parsed = urlparse(url)
    # Params can live in the fragment (SPA routing) or the query string.
    candidates = []
    if parsed.fragment:
        frag = parsed.fragment
        if "?" in frag:
            candidates.append(parse_qs(frag.split("?", 1)[1]))
    if parsed.query:
        candidates.append(parse_qs(parsed.query))
    file_id = page_id = None
    for qs in candidates:
        file_id = file_id or (qs.get("file-id", [None])[0])
        page_id = page_id or (qs.get("page-id", [None])[0])
    return file_id, page_id


def _row_to_out(row: tuple) -> TemplateOut:
    preview = None
    if row[7]:
        try:
            preview = signed_url(row[7])
        except Exception:
            preview = None
    return TemplateOut(
        id=row[0], name=row[1],
        penpot_file_id=row[2], penpot_page_id=row[3], penpot_frame_id=row[4],
        sync_status=row[5], sync_error=row[6],
        preview_url=preview,
        zones=row[8],
        last_synced_at=row[9].isoformat() if row[9] else None,
        board_name=(row[8] or {}).get("_board_name") if isinstance(row[8], dict) else None,
    )


_SELECT = (
    "id, name, penpot_file_id, penpot_page_id, penpot_frame_id, "
    "sync_status, sync_error, preview_path, zones, last_synced_at"
)


@router.get("", response_model=list[TemplateOut])
def list_templates(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            f"SELECT {_SELECT} FROM templates WHERE tenant_id = %s ORDER BY created_at DESC",
            (str(user.tenant_id),),
        ).fetchall()
    return [_row_to_out(r) for r in rows]


@router.post("", response_model=TemplateOut)
def create_template(payload: TemplateIn, user: CurrentUser = Depends(current_user)):
    file_id, page_id = _parse_penpot_url(payload.penpot_url)
    if not file_id:
        raise HTTPException(
            422,
            "Could not find file-id in that URL. Open your file in Penpot and copy the "
            "browser URL from the workspace (it contains file-id=…).",
        )
    template_id = uuid4()
    import json
    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "insert into templates (id, tenant_id, name, penpot_file_id, penpot_page_id, zones) "
            "values (%s, %s, %s, %s, %s, %s::jsonb)",
            (str(template_id), str(user.tenant_id), payload.name, file_id, page_id,
             json.dumps({"_board_name": payload.board_name})),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "template.create", "template", str(template_id)),
        )
    try:
        from workers.template_sync import sync_template
        sync_template.delay(str(user.tenant_id), str(template_id))
    except Exception:
        pass
    return TemplateOut(
        id=template_id, name=payload.name,
        penpot_file_id=file_id, penpot_page_id=page_id, penpot_frame_id=None,
        board_name=payload.board_name,
        sync_status="pending", sync_error=None, preview_url=None, zones=None,
        last_synced_at=None,
    )


@router.post("/{template_id}/sync")
def resync_template(template_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "update templates set sync_status = 'pending', sync_error = null "
            "where id = %s and tenant_id = %s",
            (str(template_id), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "template not found")
    from workers.template_sync import sync_template
    sync_template.delay(str(user.tenant_id), str(template_id))
    return {"ok": True}


@router.delete("/{template_id}")
def delete_template(template_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "delete from templates where id = %s and tenant_id = %s",
            (str(template_id), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "template not found")
    return {"ok": True}
