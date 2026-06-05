from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/brand-kit", tags=["brand-kit"])


class Persona(BaseModel):
    name: str
    age_range: str | None = None
    income_tier: str | None = None
    lifestyle: str | None = None
    preferred_imagery: str | None = None


class BrandKitIn(BaseModel):
    brand_name: str
    tone: str | None = None
    values: str | None = None
    colours: list[str] = Field(default_factory=list)
    fonts: list[str] = Field(default_factory=list)
    logo_paths: list[str] = Field(default_factory=list)
    persona_definitions: list[Persona] = Field(default_factory=list)
    asset_permission_accepted: bool = False


class BrandKitOut(BrandKitIn):
    id: UUID


@router.get("", response_model=BrandKitOut | None)
def get_brand_kit(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        cur = conn.execute(
            "SELECT id, brand_name, tone, values, colours, fonts, logo_paths, persona_definitions, "
            "asset_permission_accepted_at FROM brand_kits WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
            (str(user.tenant_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return BrandKitOut(
            id=row[0], brand_name=row[1], tone=row[2], values=row[3],
            colours=row[4], fonts=row[5], logo_paths=row[6],
            persona_definitions=row[7],
            asset_permission_accepted=row[8] is not None,
        )


@router.post("", response_model=BrandKitOut)
def upsert_brand_kit(payload: BrandKitIn, user: CurrentUser = Depends(current_user)):
    if not payload.asset_permission_accepted:
        raise HTTPException(400, "asset permission declaration required")
    personas_json: list[dict[str, Any]] = [p.model_dump() for p in payload.persona_definitions]
    import json
    with tenant_connection(user.tenant_id) as conn:
        cur = conn.execute(
            """
            insert into brand_kits (tenant_id, brand_name, tone, values, colours, fonts, logo_paths,
                                    persona_definitions, asset_permission_accepted_at)
            values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, now())
            returning id
            """,
            (
                str(user.tenant_id), payload.brand_name, payload.tone, payload.values,
                json.dumps(payload.colours), json.dumps(payload.fonts), json.dumps(payload.logo_paths),
                json.dumps(personas_json),
            ),
        )
        new_id = cur.fetchone()[0]
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id) values (%s, %s, %s, %s, %s)",
            (str(user.tenant_id), str(user.user_id), "brand_kit.upsert", "brand_kit", str(new_id)),
        )
    return BrandKitOut(id=new_id, **payload.model_dump())
