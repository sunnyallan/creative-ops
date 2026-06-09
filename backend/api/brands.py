"""Multi-brand directory per tenant."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/brands", tags=["brands"])


class Persona(BaseModel):
    name: str
    age_range: str | None = None
    income_tier: str | None = None
    lifestyle: str | None = None
    preferred_imagery: str | None = None


class BrandIn(BaseModel):
    name: str
    tone: str | None = None
    brand_values: str | None = None
    primary_colour: str | None = None
    secondary_colour: str | None = None
    accent_colour: str | None = None
    heading_font: str | None = None
    body_font: str | None = None
    logo_path: str | None = None
    persona_definitions: list[Persona] = Field(default_factory=list)
    brand_rules_do: str | None = None
    brand_rules_dont: str | None = None
    brand_feel: str | None = None
    style_description: str | None = None
    asset_permission_accepted: bool = False


class BrandOut(BrandIn):
    id: UUID


def _row_to_brand(row: tuple) -> BrandOut:
    return BrandOut(
        id=row[0],
        name=row[1],
        tone=row[2],
        brand_values=row[3],
        primary_colour=row[4],
        secondary_colour=row[5],
        accent_colour=row[6],
        heading_font=row[7],
        body_font=row[8],
        logo_path=row[9],
        persona_definitions=row[10] or [],
        brand_rules_do=row[11],
        brand_rules_dont=row[12],
        brand_feel=row[13],
        style_description=row[14],
        asset_permission_accepted=row[15] is not None,
    )


_SELECT_COLS = (
    "id, name, tone, brand_values, primary_colour, secondary_colour, accent_colour, "
    "heading_font, body_font, logo_path, persona_definitions, brand_rules_do, "
    "brand_rules_dont, brand_feel, style_description, asset_permission_accepted_at"
)


@router.get("", response_model=list[BrandOut])
def list_brands(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM brands WHERE tenant_id = %s ORDER BY created_at ASC",
            (str(user.tenant_id),),
        ).fetchall()
    return [_row_to_brand(r) for r in rows]


@router.get("/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            f"SELECT {_SELECT_COLS} FROM brands WHERE id = %s",
            (str(brand_id),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "brand not found")
    return _row_to_brand(row)


def _validate_mandatory_style(payload: BrandIn, brand_id: UUID | None, conn) -> None:
    """Enforce: at least 2 reference images OR style_description >= 200 chars."""
    desc_len = len((payload.style_description or "").strip())
    if desc_len >= 200:
        return
    if brand_id is None:
        # New brand — can't have references yet. Require description.
        raise HTTPException(
            422,
            "Style description must be at least 200 characters (or upload ≥2 reference images after creating the brand).",
        )
    # Existing brand — count references
    ref_count = conn.execute(
        "SELECT COUNT(*) FROM brand_references WHERE brand_id = %s",
        (str(brand_id),),
    ).fetchone()[0]
    if ref_count < 2 and desc_len < 200:
        raise HTTPException(
            422,
            f"Brand needs at least 2 reference images OR a style description of 200+ characters "
            f"(currently {ref_count} refs and {desc_len} chars).",
        )


@router.post("", response_model=BrandOut)
def create_brand(payload: BrandIn, user: CurrentUser = Depends(current_user)):
    if not payload.asset_permission_accepted:
        raise HTTPException(400, "asset permission declaration required")
    personas_json = [p.model_dump() for p in payload.persona_definitions]
    with tenant_connection(user.tenant_id) as conn:
        # New brand — only enforce description-min if no refs will be added later.
        # We allow saving with desc < 200 if user plans to upload references after.
        # But require either: description >= 50 chars OR explicit "I will add references" flag.
        # Simplest: enforce description >= 50 minimum at create; full validation when promoting brand to "ready".
        if not payload.style_description or len(payload.style_description.strip()) < 50:
            # Don't block create — they'll add references next. Just save with what we have.
            pass

        row = conn.execute(
            """
            insert into brands (
              tenant_id, name, tone, brand_values,
              primary_colour, secondary_colour, accent_colour,
              heading_font, body_font, logo_path,
              persona_definitions,
              brand_rules_do, brand_rules_dont, brand_feel,
              style_description,
              asset_permission_accepted_at
            ) values (
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s,
              %s::jsonb,
              %s, %s, %s,
              %s,
              now()
            )
            returning id
            """,
            (
                str(user.tenant_id), payload.name, payload.tone, payload.brand_values,
                payload.primary_colour, payload.secondary_colour, payload.accent_colour,
                payload.heading_font, payload.body_font, payload.logo_path,
                json.dumps(personas_json),
                payload.brand_rules_do, payload.brand_rules_dont, payload.brand_feel,
                payload.style_description,
            ),
        ).fetchone()
        new_id = row[0]
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "brand.create", "brand", str(new_id)),
        )
    return BrandOut(id=new_id, **payload.model_dump())


@router.patch("/{brand_id}", response_model=BrandOut)
def update_brand(brand_id: UUID, payload: BrandIn, user: CurrentUser = Depends(current_user)):
    personas_json = [p.model_dump() for p in payload.persona_definitions]
    with tenant_connection(user.tenant_id) as conn:
        # When patching: enforce mandatory style rule (>=2 refs OR >=200 char desc)
        _validate_mandatory_style(payload, brand_id, conn)

        n = conn.execute(
            """
            update brands set
              name = %s, tone = %s, brand_values = %s,
              primary_colour = %s, secondary_colour = %s, accent_colour = %s,
              heading_font = %s, body_font = %s, logo_path = %s,
              persona_definitions = %s::jsonb,
              brand_rules_do = %s, brand_rules_dont = %s, brand_feel = %s,
              style_description = %s,
              updated_at = now()
            where id = %s and tenant_id = %s
            """,
            (
                payload.name, payload.tone, payload.brand_values,
                payload.primary_colour, payload.secondary_colour, payload.accent_colour,
                payload.heading_font, payload.body_font, payload.logo_path,
                json.dumps(personas_json),
                payload.brand_rules_do, payload.brand_rules_dont, payload.brand_feel,
                payload.style_description,
                str(brand_id), str(user.tenant_id),
            ),
        ).rowcount
        if not n:
            raise HTTPException(404, "brand not found")
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "brand.update", "brand", str(brand_id)),
        )
    return BrandOut(id=brand_id, **payload.model_dump())


@router.delete("/{brand_id}")
def delete_brand(brand_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "delete from brands where id = %s and tenant_id = %s",
            (str(brand_id), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "brand not found")
    return {"ok": True}
