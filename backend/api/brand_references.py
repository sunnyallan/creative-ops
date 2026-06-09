"""Brand reference banners — uploaded by user, style auto-extracted by vision model."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/brands/{brand_id}/references", tags=["brand_references"])


class BrandReferenceIn(BaseModel):
    image_path: str  # storage path uploaded directly to Supabase by the client


class BrandReferenceOut(BaseModel):
    id: UUID
    image_path: str
    extracted_style_description: str | None
    extraction_status: str
    extraction_error: str | None


def _ensure_brand_exists(brand_id: UUID, tenant_id: UUID, conn) -> None:
    row = conn.execute(
        "SELECT 1 FROM brands WHERE id = %s AND tenant_id = %s",
        (str(brand_id), str(tenant_id)),
    ).fetchone()
    if not row:
        raise HTTPException(404, "brand not found")


@router.get("", response_model=list[BrandReferenceOut])
def list_references(brand_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        _ensure_brand_exists(brand_id, user.tenant_id, conn)
        rows = conn.execute(
            "SELECT id, image_path, extracted_style_description, extraction_status, extraction_error "
            "FROM brand_references WHERE brand_id = %s ORDER BY created_at ASC",
            (str(brand_id),),
        ).fetchall()
    return [
        BrandReferenceOut(
            id=r[0], image_path=r[1], extracted_style_description=r[2],
            extraction_status=r[3], extraction_error=r[4],
        )
        for r in rows
    ]


@router.post("", response_model=BrandReferenceOut)
def add_reference(brand_id: UUID, payload: BrandReferenceIn, user: CurrentUser = Depends(current_user)):
    ref_id = uuid4()
    with tenant_connection(user.tenant_id) as conn:
        _ensure_brand_exists(brand_id, user.tenant_id, conn)
        conn.execute(
            "insert into brand_references (id, brand_id, tenant_id, image_path) "
            "values (%s, %s, %s, %s)",
            (str(ref_id), str(brand_id), str(user.tenant_id), payload.image_path),
        )

    # Kick the vision extractor (Celery task). Failure to enqueue is non-fatal — user can retry.
    try:
        from workers.style_extractor import extract_reference_style
        extract_reference_style.delay(str(user.tenant_id), str(brand_id), str(ref_id))
    except Exception:
        pass

    return BrandReferenceOut(
        id=ref_id, image_path=payload.image_path, extracted_style_description=None,
        extraction_status="pending", extraction_error=None,
    )


@router.delete("/{ref_id}")
def delete_reference(brand_id: UUID, ref_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        _ensure_brand_exists(brand_id, user.tenant_id, conn)
        n = conn.execute(
            "delete from brand_references where id = %s and brand_id = %s",
            (str(ref_id), str(brand_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "reference not found")
    return {"ok": True}


@router.post("/regenerate")
def regenerate_aggregate(brand_id: UUID, user: CurrentUser = Depends(current_user)):
    """Re-aggregate brand.style_description from all completed reference extractions."""
    with tenant_connection(user.tenant_id) as conn:
        _ensure_brand_exists(brand_id, user.tenant_id, conn)
        rows = conn.execute(
            "SELECT extracted_style_description FROM brand_references "
            "WHERE brand_id = %s AND extraction_status = 'done' "
            "AND extracted_style_description IS NOT NULL",
            (str(brand_id),),
        ).fetchall()
        descriptions = [r[0] for r in rows if r[0]]
        if not descriptions:
            raise HTTPException(400, "no completed extractions yet")
        aggregated = "\n\n---\n\n".join(descriptions)
        conn.execute(
            "UPDATE brands SET style_description = %s, updated_at = now() WHERE id = %s",
            (aggregated, str(brand_id)),
        )
    return {"ok": True, "char_count": len(aggregated)}
