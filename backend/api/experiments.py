"""v4.0 Phase B — Experiments API (autonomous growth loop).

Contract:
  POST /experiments           create + start (status → 'running')
  GET  /experiments           list (headline stats)
  GET  /experiments/{id}      full detail (iterations + spend + metrics)
  POST /experiments/{id}/approve-iteration    approve the pending awaiting_approval iteration
  POST /experiments/{id}/pause
  POST /experiments/{id}/resume
  POST /experiments/{id}/stop  kill switch — cancels any in-flight ad
  POST /experiments/{id}/tick  operator-triggered advance (belt-and-braces vs beat)
  GET  /experiments/{id}/report
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/experiments", tags=["experiments"])

# ============================================================
# Schemas
# ============================================================

_ALLOWED_METRICS = {"ctr", "reach", "impressions", "clicks", "conversions",
                    "engagement", "followers", "spend"}
_ALLOWED_CHANNELS = {"mock_ads", "meta_ads", "instagram_organic", "facebook_organic"}


class ExperimentIn(BaseModel):
    goal: str = Field(min_length=8)
    goal_metric: str
    goal_target: float | None = None
    budget_total: float = Field(gt=0)
    per_iteration_cap: float | None = None
    channels: list[str] = Field(default_factory=lambda: ["mock_ads"])
    brand_id: UUID | None = None
    # Numeric so demos can set fractional windows (e.g. 0.0833 = 5 minutes).
    # Min 0.01 (~36s), max 168 (7 days).
    metric_window_hours: float = Field(48, ge=0.01, le=168)
    min_spend_for_verdict: float = Field(100.0, ge=0)
    max_iterations: int = Field(20, ge=1, le=100)


class ExperimentOut(BaseModel):
    id: UUID
    brand_id: UUID | None
    goal: str
    goal_metric: str
    goal_target: float | None
    budget_total: float
    budget_spent: float
    budget_committed: float
    per_iteration_cap: float | None
    channels: list[str]
    status: str
    metric_window_hours: float
    min_spend_for_verdict: float
    max_iterations: int
    created_at: str
    updated_at: str
    latest_report: dict | None = None


class IterationOut(BaseModel):
    id: UUID
    index: int
    status: str
    hypothesis: str | None
    format: str | None
    channel: str
    persona: str | None
    spend_planned: float
    spend_actual: float
    campaign_id: UUID | None
    metrics: dict | None
    metrics_history: list | None
    verdict: dict | None
    applied_learnings: list | None
    publish_ref: dict | None
    published_at: str | None
    measured_at: str | None
    measure_deadline: str | None
    error: str | None


class ExperimentDetail(ExperimentOut):
    iterations: list[IterationOut]


# ============================================================
# Row -> model
# ============================================================

_EXP_COLS = ("id, brand_id, goal, goal_metric, goal_target, budget_total, "
             "budget_spent, budget_committed, per_iteration_cap, channels, "
             "status, metric_window_hours, min_spend_for_verdict, max_iterations, "
             "created_at, updated_at, report")


def _row_to_experiment(r: tuple) -> ExperimentOut:
    return ExperimentOut(
        id=r[0], brand_id=r[1], goal=r[2], goal_metric=r[3],
        goal_target=float(r[4]) if r[4] is not None else None,
        budget_total=float(r[5]), budget_spent=float(r[6]),
        budget_committed=float(r[7]),
        per_iteration_cap=float(r[8]) if r[8] is not None else None,
        channels=list(r[9] or []), status=r[10],
        metric_window_hours=float(r[11]), min_spend_for_verdict=float(r[12]),
        max_iterations=int(r[13]),
        created_at=r[14].isoformat(), updated_at=r[15].isoformat(),
        latest_report=r[16],
    )


_ITER_COLS = ("id, index, status, hypothesis, format, channel, persona, "
              "spend_planned, spend_actual, campaign_id, metrics, metrics_history, "
              "verdict, applied_learnings, publish_ref, published_at, measured_at, "
              "measure_deadline, error")


def _row_to_iteration(r: tuple) -> IterationOut:
    return IterationOut(
        id=r[0], index=int(r[1]), status=r[2], hypothesis=r[3],
        format=r[4], channel=r[5], persona=r[6],
        spend_planned=float(r[7] or 0), spend_actual=float(r[8] or 0),
        campaign_id=r[9], metrics=r[10], metrics_history=r[11],
        verdict=r[12], applied_learnings=r[13], publish_ref=r[14],
        published_at=r[15].isoformat() if r[15] else None,
        measured_at=r[16].isoformat() if r[16] else None,
        measure_deadline=r[17].isoformat() if r[17] else None,
        error=r[18],
    )


# ============================================================
# Endpoints
# ============================================================

@router.post("", response_model=ExperimentOut)
def create_experiment(payload: ExperimentIn, user: CurrentUser = Depends(current_user)):
    if payload.goal_metric not in _ALLOWED_METRICS:
        raise HTTPException(422, f"goal_metric must be one of {sorted(_ALLOWED_METRICS)}")
    bad = [c for c in payload.channels if c not in _ALLOWED_CHANNELS]
    if bad:
        raise HTTPException(422, f"unknown channels: {bad}")
    if payload.per_iteration_cap is not None and payload.per_iteration_cap > payload.budget_total:
        raise HTTPException(422, "per_iteration_cap cannot exceed budget_total")

    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "INSERT INTO experiments (tenant_id, brand_id, goal, goal_metric, goal_target, "
            "budget_total, per_iteration_cap, channels, status, metric_window_hours, "
            "min_spend_for_verdict, max_iterations) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'running', %s, %s, %s) "
            "RETURNING " + _EXP_COLS,
            (str(user.tenant_id), str(payload.brand_id) if payload.brand_id else None,
             payload.goal, payload.goal_metric, payload.goal_target,
             payload.budget_total, payload.per_iteration_cap,
             payload.channels, payload.metric_window_hours,
             payload.min_spend_for_verdict, payload.max_iterations),
        ).fetchone()
        exp = _row_to_experiment(r)
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'experiment.create', 'experiment', %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), str(exp.id),
             json.dumps(payload.model_dump(), default=str)),
        )

    # Kick the first step asynchronously via the tick — keeps the API response fast.
    try:
        from workers.orchestrator_tick import orchestrator_tick
        orchestrator_tick.delay()
    except Exception:
        pass
    return exp


@router.get("", response_model=list[ExperimentOut])
def list_experiments(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            f"SELECT {_EXP_COLS} FROM experiments WHERE tenant_id = %s "
            "ORDER BY updated_at DESC",
            (str(user.tenant_id),),
        ).fetchall()
    return [_row_to_experiment(r) for r in rows]


@router.get("/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            f"SELECT {_EXP_COLS} FROM experiments WHERE id = %s AND tenant_id = %s",
            (str(experiment_id), str(user.tenant_id)),
        ).fetchone()
        if not r:
            raise HTTPException(404, "experiment not found")
        exp = _row_to_experiment(r)
        iter_rows = conn.execute(
            f"SELECT {_ITER_COLS} FROM experiment_iterations "
            "WHERE experiment_id = %s ORDER BY index ASC",
            (str(experiment_id),),
        ).fetchall()
    return ExperimentDetail(**exp.model_dump(),
                            iterations=[_row_to_iteration(x) for x in iter_rows])


@router.post("/{experiment_id}/pause")
def pause(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE experiments SET status = 'paused', updated_at = now() "
            "WHERE id = %s AND tenant_id = %s AND status IN ('running','awaiting_approval')",
            (str(experiment_id), str(user.tenant_id)),
        ).rowcount
        if n:
            conn.execute(
                "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
                "values (%s, %s, 'experiment.pause', 'experiment', %s)",
                (str(user.tenant_id), str(user.user_id), str(experiment_id)),
            )
    if not n:
        raise HTTPException(409, "experiment not pausable in its current status")
    return {"ok": True}


@router.post("/{experiment_id}/resume")
def resume(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE experiments SET status = 'running', updated_at = now() "
            "WHERE id = %s AND tenant_id = %s AND status IN ('paused','awaiting_approval')",
            (str(experiment_id), str(user.tenant_id)),
        ).rowcount
        if n:
            conn.execute(
                "insert into audit_log (tenant_id, user_id, action, entity, entity_id) "
                "values (%s, %s, 'experiment.resume', 'experiment', %s)",
                (str(user.tenant_id), str(user.user_id), str(experiment_id)),
            )
    if not n:
        raise HTTPException(409, "not resumable")
    try:
        from workers.orchestrator_tick import orchestrator_tick
        orchestrator_tick.delay()
    except Exception:
        pass
    return {"ok": True}


@router.post("/{experiment_id}/stop")
def stop(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    """Kill switch — cancels any in-flight publications and closes the experiment."""
    from integrations.mock_ads import get_adapter

    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "SELECT status FROM experiments WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (str(experiment_id), str(user.tenant_id)),
        ).fetchone()
        if not r:
            raise HTTPException(404, "experiment not found")
        if r[0] in ("stopped", "goal_met", "budget_exhausted", "failed"):
            return {"ok": True, "already": r[0]}

        # Cancel every non-terminal iteration
        in_flight = conn.execute(
            "SELECT id, channel, publish_ref, spend_planned FROM experiment_iterations "
            "WHERE experiment_id = %s AND status IN ('publishing','published','measuring')",
            (str(experiment_id),),
        ).fetchall()
        for iter_id, channel, publish_ref, spend_planned in in_flight:
            try:
                get_adapter(channel or "mock_ads").cancel(publish_ref or {})
            except Exception:
                pass
            conn.execute(
                "UPDATE experiment_iterations SET status = 'skipped', "
                "error = 'experiment stopped by user' WHERE id = %s",
                (str(iter_id),),
            )
            # Release any still-committed budget from the ledger
            if spend_planned:
                conn.execute(
                    "UPDATE experiments SET budget_committed = GREATEST(0, budget_committed - %s) "
                    "WHERE id = %s",
                    (float(spend_planned), str(experiment_id)),
                )

        conn.execute(
            "UPDATE experiments SET status = 'stopped', updated_at = now() WHERE id = %s",
            (str(experiment_id),),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'experiment.stop', 'experiment', %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), str(experiment_id),
             json.dumps({"in_flight_cancelled": len(in_flight)})),
        )
    return {"ok": True, "in_flight_cancelled": len(in_flight)}


@router.post("/{experiment_id}/approve-iteration")
def approve_iteration(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    """One-click approve for the pending awaiting_approval iteration."""
    from agents.orchestrator import commit_planned_spend, BudgetError

    with tenant_connection(user.tenant_id) as conn:
        it = conn.execute(
            "SELECT id, spend_planned FROM experiment_iterations "
            "WHERE experiment_id = %s AND status = 'awaiting_approval' "
            "ORDER BY index ASC LIMIT 1",
            (str(experiment_id),),
        ).fetchone()
        if not it:
            raise HTTPException(404, "no iteration awaiting approval")
        iter_id, planned = it
    try:
        commit_planned_spend(user.tenant_id, str(experiment_id), float(planned))
    except BudgetError as e:
        raise HTTPException(409, str(e))
    with tenant_connection(user.tenant_id) as conn:
        conn.execute(
            "UPDATE experiment_iterations SET status = 'planning' WHERE id = %s",
            (str(iter_id),),
        )
        conn.execute(
            "UPDATE experiments SET status = 'running', updated_at = now() WHERE id = %s",
            (str(experiment_id),),
        )
        conn.execute(
            "insert into audit_log (tenant_id, user_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'iteration.approved', 'iteration', %s, %s::jsonb)",
            (str(user.tenant_id), str(user.user_id), str(iter_id),
             json.dumps({"planned": float(planned)})),
        )
    try:
        from workers.orchestrator_tick import orchestrator_tick
        orchestrator_tick.delay()
    except Exception:
        pass
    return {"ok": True, "iteration_id": str(iter_id)}


@router.post("/{experiment_id}/tick")
def tick(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    """Operator-triggered advance. Useful in demos where the 15-min beat
    tick is too slow, and for troubleshooting. Runs synchronously."""
    from agents.orchestrator import run_next_step
    result = run_next_step(str(user.tenant_id), str(experiment_id))
    return result


@router.get("/{experiment_id}/report")
def get_report(experiment_id: UUID, user: CurrentUser = Depends(current_user)):
    from agents.orchestrator import build_report

    with tenant_connection(user.tenant_id) as conn:
        r = conn.execute(
            "SELECT status, report FROM experiments WHERE id = %s AND tenant_id = %s",
            (str(experiment_id), str(user.tenant_id)),
        ).fetchone()
        if not r:
            raise HTTPException(404, "experiment not found")
    status, report = r
    if not report:
        # Generate on-demand even for still-running experiments
        report = build_report(user.tenant_id, str(experiment_id))
    return {"status": status, "report": report}
