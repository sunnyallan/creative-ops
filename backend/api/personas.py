"""Predefined persona library — global, read-only."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/personas", tags=["personas"])


class LibraryPersona(BaseModel):
    id: str
    name: str
    age_range: str | None
    income_tier: str | None
    lifestyle: str | None
    preferred_imagery: str | None
    tags: list[str]


@router.get("/library", response_model=list[LibraryPersona])
def list_library(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            "SELECT id, name, age_range, income_tier, lifestyle, preferred_imagery, tags "
            "FROM personas_library ORDER BY name"
        ).fetchall()
    return [
        LibraryPersona(
            id=str(r[0]), name=r[1], age_range=r[2], income_tier=r[3],
            lifestyle=r[4], preferred_imagery=r[5], tags=list(r[6] or []),
        )
        for r in rows
    ]
