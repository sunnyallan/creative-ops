import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CopyConstraints(BaseModel):
    headline_max_chars: int = Field(60, ge=10, le=200)
    body_max_chars: int = Field(120, ge=20, le=500)
    cta_max_chars: int = Field(25, ge=5, le=60)


class PartnerBrand(BaseModel):
    name: str
    logo_path: str | None = None
    primary_colour: str | None = None
    # Comma-separated transactable products. e.g. "flights, hotels, trains, buses, holiday packages"
    products_or_services: str | None = None


class CampaignIn(BaseModel):
    goal: str
    persona_segment: str | None = None  # legacy single-persona, still supported
    persona_segments: list[str] = Field(default_factory=list)  # NEW: multi
    copy_constraints: CopyConstraints = Field(default_factory=CopyConstraints)
    partner_brand: PartnerBrand | None = None


class CampaignOut(BaseModel):
    id: UUID
    goal: str
    persona_segment: str | None
    persona_segments: list[str] = Field(default_factory=list)
    status: str
    brief: list[dict] | None
    copy_constraints: CopyConstraints
    partner_brand: PartnerBrand | None = None


@router.post("", response_model=CampaignOut)
def create_campaign(payload: CampaignIn, user: CurrentUser = Depends(current_user)):
    campaign_id = uuid4()
    partner_json = json.dumps(payload.partner_brand.model_dump()) if payload.partner_brand else None
    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "insert into campaigns (id, tenant_id, goal, persona_segment, status, copy_constraints, partner_brand) "
            "values (%s, %s, %s, %s, 'briefing', %s::jsonb, %s::jsonb)",
            (
                str(campaign_id), str(user.tenant_id), payload.goal, payload.persona_segment,
                json.dumps(payload.copy_constraints.model_dump()),
                partner_json,
            ),
        )
        # Auto-save / refresh the partner record so it's reusable next time
        if payload.partner_brand:
            pb = payload.partner_brand
            conn.execute(
                """
                insert into partners (tenant_id, name, logo_path, primary_colour, products_or_services)
                values (%s, %s, %s, %s, %s)
                on conflict (tenant_id, name) do update set
                    logo_path = coalesce(excluded.logo_path, partners.logo_path),
                    primary_colour = coalesce(excluded.primary_colour, partners.primary_colour),
                    products_or_services = coalesce(excluded.products_or_services, partners.products_or_services),
                    updated_at = now()
                """,
                (str(user.tenant_id), pb.name, pb.logo_path, pb.primary_colour, pb.products_or_services),
            )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "campaign.create", "campaign", str(campaign_id)),
        )

    from agents.briefing_agent import run_briefing
    # Resolve the list of personas — explicit list wins, else fall back to legacy single field
    personas = payload.persona_segments or ([payload.persona_segment] if payload.persona_segment else [None])

    all_briefs: list[dict] = []
    for persona in personas:
        per_persona_briefs = run_briefing(
            user.tenant_id, campaign_id, payload.goal, persona,
            payload.copy_constraints.model_dump(),
            partner_brand=(payload.partner_brand.model_dump() if payload.partner_brand else None),
        )
        # Tag each brief with its persona so the worker can find it
        for b in per_persona_briefs:
            b["persona_segment"] = persona or b.get("persona_segment")
        all_briefs.extend(per_persona_briefs)

    # Persist the combined brief list
    import json as _json
    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "UPDATE campaigns SET brief = %s::jsonb, status = 'briefed' WHERE id = %s",
            (_json.dumps(all_briefs), str(campaign_id)),
        )

    from workers.creative import generate_creative
    for i in range(len(all_briefs)):
        generate_creative.delay(str(user.tenant_id), str(campaign_id), i)

    return CampaignOut(
        id=campaign_id, goal=payload.goal,
        persona_segment=payload.persona_segment,
        persona_segments=payload.persona_segments,
        status="briefed", brief=all_briefs, copy_constraints=payload.copy_constraints,
        partner_brand=payload.partner_brand,
    )


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT id, goal, persona_segment, status, brief, copy_constraints, partner_brand FROM campaigns WHERE id = %s",
            (str(campaign_id),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "campaign not found")
    return CampaignOut(
        id=row[0], goal=row[1], persona_segment=row[2], status=row[3], brief=row[4],
        copy_constraints=CopyConstraints(**row[5]) if row[5] else CopyConstraints(),
        partner_brand=PartnerBrand(**row[6]) if row[6] else None,
        persona_segments=list({b.get("persona_segment") for b in (row[4] or []) if b.get("persona_segment")}),
    )
