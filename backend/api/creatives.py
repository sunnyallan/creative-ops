import base64
import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection
from storage import signed_url, upload_bytes

router = APIRouter(prefix="/creatives", tags=["creatives"])


class CreativeOut(BaseModel):
    id: UUID
    campaign_id: UUID
    channel: str
    dimensions: str
    headline: str | None
    body: str | None
    cta: str | None
    image_url: str | None
    governance_status: str
    governance_issues: dict | list | None
    human_status: str
    human_rejection_reason: str | None
    human_rejection_tag: str | None
    persona_segment: str | None = None
    slide_index: int = 0
    layout_style: str | None = None


class RejectIn(BaseModel):
    reason: str
    tag: str | None = None


def _row_to_creative(row: tuple) -> CreativeOut:
    image_url = None
    if row[8]:
        try:
            image_url = signed_url(row[8])
        except Exception:
            image_url = None
    return CreativeOut(
        id=row[0], campaign_id=row[1], channel=row[2], dimensions=row[3],
        headline=row[4], body=row[5], cta=row[6], image_url=image_url,
        governance_status=row[9], governance_issues=row[10],
        human_status=row[11], human_rejection_reason=row[12], human_rejection_tag=row[13],
        persona_segment=row[14] if len(row) > 14 else None,
        slide_index=row[15] if len(row) > 15 else 0,
        layout_style=row[16] if len(row) > 16 else None,
    )


@router.get("", response_model=list[CreativeOut])
def list_creatives(
    status: str | None = None,
    campaign_id: UUID | None = None,
    user: CurrentUser = Depends(current_user),
):
    q = (
        "SELECT id, campaign_id, channel, dimensions, copy_headline, copy_body, copy_cta, "
        "tenant_id, storage_path, governance_status, governance_issues, "
        "human_status, human_rejection_reason, human_rejection_tag, persona_segment, slide_index, layout_style "
        "FROM creatives WHERE tenant_id = %s"
    )
    args: list = [str(user.tenant_id)]
    if campaign_id:
        q += " AND campaign_id = %s"
        args.append(str(campaign_id))
    if status == "pending_review":
        # Show anything not yet acted on by a human, regardless of governance state.
        # Blocked ones are filtered out (Sightengine hard-block).
        q += " AND human_status = 'pending' AND governance_status <> 'blocked' AND storage_path IS NOT NULL"
    elif status:
        q += " AND human_status = %s"
        args.append(status)
    q += " ORDER BY created_at DESC LIMIT 200"
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(q, args).fetchall()
    return [_row_to_creative(r) for r in rows]


@router.post("/{creative_id}/approve")
def approve(creative_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "UPDATE creatives SET human_status = 'approved' WHERE id = %s "
            "RETURNING channel, storage_path, copy_headline, copy_body, copy_cta",
            (str(creative_id),),
        ).fetchone()
        if not row:
            raise HTTPException(404, "creative not found")
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "creative.approve", "creative", str(creative_id)),
        )
    # Route to stub deployer
    from integrations import dispatch
    dispatch(
        tenant_id=user.tenant_id,
        creative_id=creative_id,
        channel=row[0],
        storage_path=row[1],
        copy={"headline": row[2], "body": row[3], "cta": row[4]},
    )
    return {"ok": True}


class EditDataOut(BaseModel):
    id: UUID
    dimensions: str
    background_url: str | None   # text-free base to draw editable text over
    fallback_url: str | None     # composed image (used if no background available)
    headline: str | None
    body: str | None
    cta: str | None
    brand_colour: str | None
    edit_layout: dict | None     # saved text-layer positions from a prior edit
    editable: bool               # false when no text-free background exists


@router.get("/{creative_id}/edit-data", response_model=EditDataOut)
def get_edit_data(creative_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT c.dimensions, c.edit_background_path, c.storage_path, "
            "c.copy_headline, c.copy_body, c.copy_cta, c.edit_layout, c.brand_id "
            "FROM creatives c WHERE c.id = %s AND c.tenant_id = %s",
            (str(creative_id), str(user.tenant_id)),
        ).fetchone()
        if not row:
            raise HTTPException(404, "creative not found")
        brand_colour = None
        if row[7]:
            b = conn.execute(
                "SELECT primary_colour FROM brands WHERE id = %s", (str(row[7]),),
            ).fetchone()
            brand_colour = b[0] if b else None

    def _url(p):
        if not p:
            return None
        try:
            return signed_url(p)
        except Exception:
            return None

    return EditDataOut(
        id=creative_id,
        dimensions=row[0],
        background_url=_url(row[1]),
        fallback_url=_url(row[2]),
        headline=row[3], body=row[4], cta=row[5],
        brand_colour=brand_colour,
        edit_layout=row[6],
        editable=bool(row[1]),
    )


class EditSaveIn(BaseModel):
    image_data_url: str          # data:image/webp;base64,… composited in the browser
    edit_layout: dict            # text-layer positions to persist for re-editing


@router.post("/{creative_id}/edit")
def save_edit(creative_id: UUID, payload: EditSaveIn, user: CurrentUser = Depends(current_user)):
    # Decode the browser-composited image
    data = payload.image_data_url
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        img_bytes = base64.b64decode(data)
    except Exception:
        raise HTTPException(400, "invalid image data")
    if len(img_bytes) > 8_000_000:
        raise HTTPException(413, "edited image too large")

    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT campaign_id FROM creatives WHERE id = %s AND tenant_id = %s",
            (str(creative_id), str(user.tenant_id)),
        ).fetchone()
        if not row:
            raise HTTPException(404, "creative not found")
        campaign_id = row[0]

    import json as _json
    path = f"tenants/{user.tenant_id}/creatives/{campaign_id}/{creative_id}_edited_{_uuid.uuid4().hex[:8]}.webp"
    try:
        upload_bytes(path, img_bytes, "image/webp")
    except Exception as e:
        raise HTTPException(500, f"upload failed: {e}")

    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "UPDATE creatives SET storage_path = %s, edit_layout = %s::jsonb WHERE id = %s",
            (path, _json.dumps(payload.edit_layout), str(creative_id)),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "creative.edited", "creative", str(creative_id)),
        )
    return {"ok": True, "image_url": signed_url(path)}


@router.post("/{creative_id}/reject")
def reject(creative_id: UUID, payload: RejectIn, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE creatives SET human_status = 'rejected', human_rejection_reason = %s, "
            "human_rejection_tag = %s WHERE id = %s",
            (payload.reason, payload.tag, str(creative_id)),
        ).rowcount
        if not n:
            raise HTTPException(404, "creative not found")
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, %s, %s, %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), "creative.reject", "creative", str(creative_id),
             '{"reason":"' + payload.reason.replace('"', '\\"') + '"}'),
        )
    return {"ok": True}
