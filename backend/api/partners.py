"""Reusable partner directory per tenant."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/partners", tags=["partners"])


class PartnerIn(BaseModel):
    name: str
    logo_path: str | None = None
    primary_colour: str | None = None
    products_or_services: str | None = None


class PartnerOut(PartnerIn):
    id: UUID


@router.get("", response_model=list[PartnerOut])
def list_partners(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            "SELECT id, name, logo_path, primary_colour, products_or_services "
            "FROM partners WHERE tenant_id = %s ORDER BY name",
            (str(user.tenant_id),),
        ).fetchall()
    return [
        PartnerOut(id=r[0], name=r[1], logo_path=r[2], primary_colour=r[3], products_or_services=r[4])
        for r in rows
    ]


@router.post("", response_model=PartnerOut)
def upsert_partner(payload: PartnerIn, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            """
            insert into partners (tenant_id, name, logo_path, primary_colour, products_or_services)
            values (%s, %s, %s, %s, %s)
            on conflict (tenant_id, name) do update set
                logo_path = coalesce(excluded.logo_path, partners.logo_path),
                primary_colour = coalesce(excluded.primary_colour, partners.primary_colour),
                products_or_services = coalesce(excluded.products_or_services, partners.products_or_services),
                updated_at = now()
            returning id
            """,
            (
                str(user.tenant_id), payload.name, payload.logo_path,
                payload.primary_colour, payload.products_or_services,
            ),
        ).fetchone()
    return PartnerOut(id=row[0], **payload.model_dump())


@router.delete("/{partner_id}")
def delete_partner(partner_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "delete from partners where id = %s and tenant_id = %s",
            (str(partner_id), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "partner not found")
    return {"ok": True}
