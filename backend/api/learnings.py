"""v4.0 Phase A — Learnings API.
Read/filter/delete learnings; power the /learnings UI library in Phase E.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/learnings", tags=["learnings"])


class LearningOut(BaseModel):
    id: UUID
    brand_id: UUID | None
    dimension: str
    statement: str
    confidence: float
    times_applied: int
    evidence: list | dict | None
    last_validated_at: str | None
    created_at: str
    superseded_by: UUID | None


def _row(r: tuple) -> LearningOut:
    return LearningOut(
        id=r[0], brand_id=r[1], dimension=r[2], statement=r[3],
        confidence=float(r[4]), times_applied=int(r[5] or 0),
        evidence=r[6],
        last_validated_at=r[7].isoformat() if r[7] else None,
        created_at=r[8].isoformat(),
        superseded_by=r[9],
    )


_SELECT = ("id, brand_id, dimension, statement, confidence, times_applied, "
           "evidence, last_validated_at, created_at, superseded_by")


@router.get("", response_model=list[LearningOut])
def list_learnings(
    user: CurrentUser = Depends(current_user),
    brand_id: UUID | None = Query(None),
    dimension: str | None = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
):
    clauses = ["tenant_id = %s", "superseded_by IS NULL", "confidence >= %s"]
    params: list = [str(user.tenant_id), min_confidence]
    if brand_id is not None:
        clauses.append("brand_id = %s")
        params.append(str(brand_id))
    if dimension:
        clauses.append("dimension = %s")
        params.append(dimension)
    sql = (f"SELECT {_SELECT} FROM learnings WHERE " + " AND ".join(clauses)
           + " ORDER BY confidence DESC, times_applied DESC, updated_at DESC LIMIT %s")
    params.append(limit)
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row(r) for r in rows]


@router.get("/{learning_id}", response_model=LearningOut)
def get_learning(learning_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            f"SELECT {_SELECT} FROM learnings WHERE id = %s AND tenant_id = %s",
            (str(learning_id), str(user.tenant_id)),
        ).fetchone()
    if not r:
        raise HTTPException(404, "learning not found")
    return _row(r)


@router.delete("/{learning_id}")
def delete_learning(learning_id: UUID, user: CurrentUser = Depends(current_user)):
    """Manual override: purge a learning that operators know is misleading."""
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "DELETE FROM learnings WHERE id = %s AND tenant_id = %s",
            (str(learning_id), str(user.tenant_id)),
        ).rowcount
        if n:
            conn.execute(
                "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
                "values (%s, %s, %s, %s, %s)",
                (str(user.tenant_id), str(user.user_id), "learning.delete", "learning", str(learning_id)),
            )
    if not n:
        raise HTTPException(404, "learning not found")
    return {"ok": True}
