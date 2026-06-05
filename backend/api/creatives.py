from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection
from storage import signed_url

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
        "human_status, human_rejection_reason, human_rejection_tag, persona_segment "
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
