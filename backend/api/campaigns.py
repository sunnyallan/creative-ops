import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

layouts_router = APIRouter(prefix="/layouts", tags=["layouts"])


@layouts_router.get("")
def list_layouts(user: CurrentUser = Depends(current_user)):
    """The 20 built-in layout styles for the campaign form picker."""
    from layouts import registry_for_api
    return registry_for_api()


class CopyConstraints(BaseModel):
    headline_max_chars: int = Field(30, ge=10, le=200)
    body_max_chars: int = Field(50, ge=20, le=500)
    cta_max_chars: int = Field(15, ge=5, le=60)


class PartnerBrand(BaseModel):
    name: str
    logo_path: str | None = None
    primary_colour: str | None = None
    # Comma-separated transactable products. e.g. "flights, hotels, trains, buses, holiday packages"
    products_or_services: str | None = None


class CampaignIn(BaseModel):
    goal: str
    brand_id: UUID | None = None  # v2.0 — multi-brand
    product_image_path: str | None = None  # v2.0 — optional hero product image
    persona_segment: str | None = None  # legacy single-persona, still supported
    persona_segments: list[str] = Field(default_factory=list)  # multi
    copy_constraints: CopyConstraints = Field(default_factory=CopyConstraints)
    partner_brand: PartnerBrand | None = None
    # v2.2 — social content types + research
    content_type: str = Field("banner")  # banner | social_post | social_carousel
    research_topic: str | None = None
    carousel_slide_count: int = Field(1, ge=1, le=10)
    # v3.0 — layout engine + custom templates
    layout_style: str = Field("auto")  # 'auto' or a key from layouts.LAYOUTS
    template_id: UUID | None = None    # synced Penpot template (overrides layout)


class CampaignOut(BaseModel):
    id: UUID
    goal: str
    brand_id: UUID | None = None
    product_image_path: str | None = None
    persona_segment: str | None
    persona_segments: list[str] = Field(default_factory=list)
    status: str
    brief: list[dict] | None
    copy_constraints: CopyConstraints
    partner_brand: PartnerBrand | None = None
    content_type: str = "banner"
    research_topic: str | None = None
    research_notes: str | None = None
    carousel_slide_count: int = 1
    layout_style: str = "auto"
    template_id: UUID | None = None


@router.post("", response_model=CampaignOut)
def create_campaign(payload: CampaignIn, user: CurrentUser = Depends(current_user)):
    campaign_id = uuid4()
    partner_json = json.dumps(payload.partner_brand.model_dump()) if payload.partner_brand else None
    with tenant_connection(user.tenant_id) as conn:
        # Resolve brand_id — explicit > most recent brand
        brand_id = payload.brand_id
        if brand_id is None:
            row = conn.execute(
                "SELECT id FROM brands WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                (str(user.tenant_id),),
            ).fetchone()
            brand_id = row[0] if row else None
        # Carousel implies social_carousel and ≥3 slides
        slide_count = payload.carousel_slide_count if payload.content_type == "social_carousel" else 1
        conn.execute(
            "insert into campaigns (id, tenant_id, brand_id, goal, persona_segment, status, "
            "copy_constraints, partner_brand, product_image_path, "
            "content_type, research_topic, carousel_slide_count, layout_style, template_id) "
            "values (%s, %s, %s, %s, %s, 'briefing', %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)",
            (
                str(campaign_id), str(user.tenant_id), str(brand_id) if brand_id else None,
                payload.goal, payload.persona_segment,
                json.dumps(payload.copy_constraints.model_dump()),
                partner_json, payload.product_image_path,
                payload.content_type, payload.research_topic, slide_count,
                payload.layout_style,
                str(payload.template_id) if payload.template_id else None,
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

    # Optional research step (synchronous before briefing — needs the notes available).
    research_notes_text: str | None = None
    if payload.research_topic:
        from workers.research import gather_research
        try:
            result = gather_research(str(user.tenant_id), str(campaign_id))
            if result.get("ok"):
                with tenant_connection(user.tenant_id) as conn:
                    rn = conn.execute(
                        "SELECT research_notes FROM campaigns WHERE id = %s",
                        (str(campaign_id),),
                    ).fetchone()
                    research_notes_text = rn[0] if rn else None
        except Exception:
            research_notes_text = None

    from agents.briefing_agent import run_briefing
    # Resolve the list of personas — explicit list wins, else fall back to legacy single field
    personas = payload.persona_segments or ([payload.persona_segment] if payload.persona_segment else [None])

    all_briefs: list[dict] = []
    for persona in personas:
        per_persona_briefs = run_briefing(
            user.tenant_id, campaign_id, payload.goal, persona,
            payload.copy_constraints.model_dump(),
            partner_brand=(payload.partner_brand.model_dump() if payload.partner_brand else None),
            brand_id=brand_id,
            content_type=payload.content_type,
            research_notes=research_notes_text,
            carousel_slide_count=slide_count,
            layout_style=payload.layout_style,
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
        brand_id=brand_id,
        product_image_path=payload.product_image_path,
        persona_segment=payload.persona_segment,
        persona_segments=payload.persona_segments,
        status="briefed", brief=all_briefs, copy_constraints=payload.copy_constraints,
        partner_brand=payload.partner_brand,
        content_type=payload.content_type,
        research_topic=payload.research_topic,
        research_notes=research_notes_text,
        carousel_slide_count=slide_count,
        layout_style=payload.layout_style,
        template_id=payload.template_id,
    )


@router.post("/{campaign_id}/regenerate-missing")
def regenerate_missing_creatives(campaign_id: UUID, user: CurrentUser = Depends(current_user)):
    """Re-fire creative.generate tasks for any brief entries that have no
    corresponding creative row yet. Useful when a worker died mid-run
    (e.g. carousel slides stuck on 'generating…')."""
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT brief FROM campaigns WHERE id = %s AND tenant_id = %s",
            (str(campaign_id), str(user.tenant_id)),
        ).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, "campaign or brief missing")
        briefs: list[dict] = row[0]

        # Which brief_index values already have a creative with storage_path?
        existing = conn.execute(
            "SELECT DISTINCT channel FROM creatives "
            "WHERE campaign_id = %s AND storage_path IS NOT NULL",
            (str(campaign_id),),
        ).fetchall()
        existing_channels = {r[0] for r in existing}

    from workers.creative import generate_creative
    fired = 0
    for i, b in enumerate(briefs):
        if b.get("channel") in existing_channels:
            continue
        generate_creative.delay(str(user.tenant_id), str(campaign_id), i)
        fired += 1
    return {"ok": True, "fired": fired, "total_briefs": len(briefs)}


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT id, goal, persona_segment, status, brief, copy_constraints, partner_brand, "
            "brand_id, product_image_path, content_type, research_topic, research_notes, "
            "carousel_slide_count, layout_style, template_id FROM campaigns WHERE id = %s",
            (str(campaign_id),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "campaign not found")
    return CampaignOut(
        id=row[0], goal=row[1], persona_segment=row[2], status=row[3], brief=row[4],
        copy_constraints=CopyConstraints(**row[5]) if row[5] else CopyConstraints(),
        partner_brand=PartnerBrand(**row[6]) if row[6] else None,
        brand_id=row[7], product_image_path=row[8],
        content_type=row[9] or "banner",
        research_topic=row[10], research_notes=row[11],
        carousel_slide_count=row[12] or 1,
        layout_style=row[13] or "auto",
        template_id=row[14],
        persona_segments=list({b.get("persona_segment") for b in (row[4] or []) if b.get("persona_segment")}),
    )
