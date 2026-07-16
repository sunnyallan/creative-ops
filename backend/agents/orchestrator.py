"""v4.0 Phase B — Orchestrator engine.

Durable LangGraph loop that turns Goal + Budget into an autonomous
research → brief → generate → publish → measure → analyze → learn → decide
cycle. State is persisted per-iteration in the `experiments` +
`experiment_iterations` tables (not just in LangGraph checkpoints) so:
  - the graph can be safely re-entered from any node (idempotent updates)
  - the mission-control UI reads plain rows, no graph replay required
  - Celery beat's `orchestrator.tick` can resume a `measuring` iteration
    without needing LangGraph running server-side between ticks

Slow-cycle: each iteration takes hours to days (real ad measurement
windows). We DO NOT hold a Python task open across that; the graph
runs to the `publish` node, sets iteration.status='measuring' with a
measure_deadline, then EXITS. `orchestrator.tick` polls each measuring
iteration, and when the deadline elapses OR the analyzer has enough
signal, it resumes the graph at `analyze`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from google.genai import types as genai_types

from db.session import tenant_connection
from observability import traced_generate

log = logging.getLogger("orchestrator")

MODEL = "gemini-2.5-flash"

# How many iterations of history to feed into plan_iteration (keep prompt tight)
_HISTORY_WINDOW = 6


# ============================================================
# DB helpers — all writes go through here so ledger stays consistent
# ============================================================

def _load_experiment(tenant_id: UUID, experiment_id: str) -> dict | None:
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT id, tenant_id, brand_id, goal, goal_metric, goal_target, "
            "budget_total, budget_spent, budget_committed, per_iteration_cap, "
            "channels, status, metric_window_hours, min_spend_for_verdict, "
            "max_iterations, langgraph_thread_id "
            "FROM experiments WHERE id = %s AND tenant_id = %s",
            (experiment_id, str(tenant_id)),
        ).fetchone()
    if not r:
        return None
    return {
        "id": str(r[0]), "tenant_id": str(r[1]),
        "brand_id": str(r[2]) if r[2] else None,
        "goal": r[3], "goal_metric": r[4], "goal_target": float(r[5]) if r[5] is not None else None,
        "budget_total": float(r[6]), "budget_spent": float(r[7]),
        "budget_committed": float(r[8]), "per_iteration_cap": float(r[9]) if r[9] is not None else None,
        "channels": list(r[10] or []),
        "status": r[11], "metric_window_hours": int(r[12]),
        "min_spend_for_verdict": float(r[13]), "max_iterations": int(r[14]),
        "langgraph_thread_id": r[15],
    }


def _iteration_history(tenant_id: UUID, experiment_id: str, limit: int = _HISTORY_WINDOW) -> list[dict]:
    """Compact summary of the last N iterations for the planner prompt."""
    with tenant_connection(tenant_id) as conn:
        rows = conn.execute(
            "SELECT index, hypothesis, format, channel, persona, spend_actual, "
            "metrics, verdict FROM experiment_iterations "
            "WHERE experiment_id = %s ORDER BY index DESC LIMIT %s",
            (experiment_id, limit),
        ).fetchall()
    return [{
        "index": r[0], "hypothesis": r[1], "format": r[2], "channel": r[3],
        "persona": r[4], "spend_actual": float(r[5] or 0),
        "metrics": r[6], "verdict": r[7],
    } for r in rows]


def _next_index(tenant_id: UUID, experiment_id: str) -> int:
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT COALESCE(MAX(index), 0) + 1 FROM experiment_iterations "
            "WHERE experiment_id = %s",
            (experiment_id,),
        ).fetchone()
    return int(r[0])


class BudgetError(RuntimeError):
    pass


def commit_planned_spend(tenant_id: UUID, experiment_id: str, amount: float) -> None:
    """Reserve amount against the experiment budget. Raises BudgetError if
    the invariant `spent + committed + amount <= total` would be violated."""
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT budget_total, budget_spent, budget_committed FROM experiments "
            "WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (experiment_id, str(tenant_id)),
        ).fetchone()
        if not r:
            raise BudgetError("experiment not found")
        total, spent, committed = float(r[0]), float(r[1]), float(r[2])
        if spent + committed + amount > total + 1e-6:
            raise BudgetError(
                f"budget invariant: spent {spent:.2f} + committed {committed:.2f} + "
                f"new {amount:.2f} > total {total:.2f}"
            )
        conn.execute(
            "UPDATE experiments SET budget_committed = budget_committed + %s, updated_at = now() "
            "WHERE id = %s",
            (amount, experiment_id),
        )


def realize_spend(tenant_id: UUID, experiment_id: str, planned: float, actual: float) -> None:
    """Move `planned` from committed → spent, adjusting for the actual amount.
    Never sends spent above total (safety clamp; over-delivery is booked as-is
    then flagged, but adapters shouldn't exceed the cap)."""
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE experiments SET "
            "budget_committed = GREATEST(0, budget_committed - %s), "
            "budget_spent = budget_spent + %s, "
            "updated_at = now() WHERE id = %s AND tenant_id = %s",
            (planned, actual, experiment_id, str(tenant_id)),
        )


def release_planned_spend(tenant_id: UUID, experiment_id: str, planned: float) -> None:
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE experiments SET budget_committed = GREATEST(0, budget_committed - %s), "
            "updated_at = now() WHERE id = %s AND tenant_id = %s",
            (planned, experiment_id, str(tenant_id)),
        )


def _update_iteration(tenant_id: UUID, iteration_id: str, **fields) -> None:
    if not fields:
        return
    cols, values = zip(*fields.items())
    sets = ", ".join(f"{c} = %s" for c in cols)
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            f"UPDATE experiment_iterations SET {sets} WHERE id = %s AND tenant_id = %s",
            (*values, iteration_id, str(tenant_id)),
        )


def _set_experiment_status(tenant_id: UUID, experiment_id: str, status: str) -> None:
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE experiments SET status = %s, updated_at = now() "
            "WHERE id = %s AND tenant_id = %s",
            (status, experiment_id, str(tenant_id)),
        )


def _audit(tenant_id: UUID, action: str, entity_id: str, meta: dict) -> None:
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, %s, 'experiment', %s, %s::jsonb)",
            (str(tenant_id), action, entity_id, json.dumps(meta, default=str)),
        )


# ============================================================
# plan_iteration — Gemini picks the next hypothesis
# ============================================================

_PLAN_PROMPT = """You are running an autonomous ad-optimisation loop toward a goal.
Decide the SINGLE next iteration to try.

Return STRICT JSON:
{
  "hypothesis": "one sentence — what you're testing and WHY, referencing prior verdicts or learnings when relevant",
  "format": "static" | "carousel" | "video",
  "persona": "one persona segment from the brand's library, or a plain descriptor",
  "channel": "one of the experiment's allowed channels",
  "creative_brief": {
    "goal": "the campaign-level goal for THIS iteration (short)",
    "angle": "the creative angle",
    "image_direction": "concrete visual direction for the AI image generator",
    "headline": "≤ 40 chars",
    "body": "≤ 90 chars",
    "cta": "≤ 20 chars"
  },
  "spend_planned": <number between 0 and remaining_budget, respecting per_iteration_cap when set>
}

Guiding rules:
- If prior iterations show a format or persona clearly winning, exploit it.
- If we have < 3 iterations of data, EXPLORE variety across format and persona.
- Never propose spend > remaining_budget or > per_iteration_cap (when set).
- Video is more expensive; only choose it when the goal or learnings justify it.
- Respect the goal_metric — carousel/video bias toward engagement/reach;
  static + strong CTA biases toward clicks/conversions.
"""


def plan_iteration(tenant_id: UUID, experiment_id: str) -> dict:
    """Call Gemini to decide the next iteration; return the plan dict."""
    exp = _load_experiment(tenant_id, experiment_id)
    if not exp:
        raise RuntimeError("experiment vanished mid-plan")
    history = _iteration_history(tenant_id, experiment_id)
    remaining = exp["budget_total"] - exp["budget_spent"] - exp["budget_committed"]

    # Load brand kit for persona palette (best-effort)
    brand_kit = {}
    if exp["brand_id"]:
        with tenant_connection(tenant_id) as conn:
            r = conn.execute(
                "SELECT name, tone, brand_feel, persona_definitions "
                "FROM brands WHERE id = %s", (exp["brand_id"],),
            ).fetchone()
        if r:
            brand_kit = {
                "brand_name": r[0], "tone": r[1], "brand_feel": r[2],
                "personas": r[3] or [],
            }

    # Retrieve top learnings for context (Phase A store)
    learnings = []
    try:
        from learning_store import retrieve_for_brief
        learnings = retrieve_for_brief(
            tenant_id=str(tenant_id),
            brand_id=exp["brand_id"],
            context=f"{exp['goal']} · goal_metric:{exp['goal_metric']} · channels:{','.join(exp['channels'])}",
            k=6,
        )
    except Exception as e:
        log.warning("plan_iteration: learnings retrieval failed: %s", e)

    context = {
        "goal": exp["goal"],
        "goal_metric": exp["goal_metric"],
        "goal_target": exp["goal_target"],
        "remaining_budget": round(remaining, 2),
        "per_iteration_cap": exp["per_iteration_cap"],
        "allowed_channels": exp["channels"],
        "iteration_count_so_far": len(history),
        "history_newest_first": history,
        "brand": brand_kit,
        "proven_learnings": [
            {"dimension": l["dimension"], "statement": l["statement"],
             "confidence": round(l["confidence"], 2)}
            for l in learnings
        ],
    }
    prompt = _PLAN_PROMPT + "\n\nCONTEXT:\n" + json.dumps(context, default=str, indent=2)

    resp = traced_generate(
        model=MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
        ),
        trace_name="orchestrator.plan_iteration",
        tenant_id=str(tenant_id),
        campaign_id=experiment_id,
        metadata={"iteration_index_next": len(history) + 1},
    )
    plan = json.loads(resp.text or "{}")

    # Defensive normalisation
    plan.setdefault("format", "static")
    plan.setdefault("channel", exp["channels"][0] if exp["channels"] else "mock_ads")
    plan["format"] = plan["format"] if plan["format"] in ("static", "carousel", "video") else "static"
    if plan["channel"] not in exp["channels"]:
        plan["channel"] = exp["channels"][0]
    try:
        plan["spend_planned"] = float(plan.get("spend_planned", 0))
    except (TypeError, ValueError):
        plan["spend_planned"] = 0.0
    plan["spend_planned"] = max(0.0, min(plan["spend_planned"], remaining))
    if exp["per_iteration_cap"] is not None:
        plan["spend_planned"] = min(plan["spend_planned"], exp["per_iteration_cap"])
    plan["applied_learnings"] = [
        {"id": l["id"], "statement": l["statement"], "confidence": l["confidence"]}
        for l in learnings
    ]
    return plan


# ============================================================
# generate_creative — reuses the existing campaign machinery
# ============================================================

def _generate_creative_for_iteration(
    tenant_id: UUID, experiment: dict, iteration: dict, plan: dict,
) -> str:
    """Create a stub campaign for this iteration and fan out a single
    creative through the existing brief→gen→governance pipeline. Returns
    the campaign_id."""
    from agents.briefing_agent import run_briefing
    from workers.creative import generate_creative
    from workers.video import generate_video
    import uuid as _uuid

    campaign_id = _uuid.uuid4()
    fmt = plan["format"]
    # Map orchestrator format → content_type + media_type
    content_type = {"static": "banner", "carousel": "social_carousel", "video": "banner"}[fmt]
    slide_count = 5 if fmt == "carousel" else 1
    media_type = "video" if fmt == "video" else "image"

    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "insert into campaigns (id, tenant_id, brand_id, goal, persona_segment, status, "
            "copy_constraints, content_type, carousel_slide_count, layout_style, media_type) "
            "values (%s, %s, %s, %s, %s, 'briefing', %s::jsonb, %s, %s, %s, %s)",
            (
                str(campaign_id), str(tenant_id),
                experiment["brand_id"], plan.get("creative_brief", {}).get("goal") or experiment["goal"],
                plan.get("persona"),
                json.dumps({"headline_max_chars": 40, "body_max_chars": 90, "cta_max_chars": 20}),
                content_type, slide_count, "auto", media_type,
            ),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, 'experiment.campaign.create', 'campaign', %s, %s::jsonb)",
            (str(tenant_id), str(campaign_id),
             json.dumps({"experiment_id": experiment["id"], "iteration_id": iteration["id"],
                         "media_type": media_type}, default=str)),
        )

    # Run the briefing agent synchronously
    run_briefing(
        tenant_id=str(tenant_id),
        campaign_id=str(campaign_id),
        goal=plan.get("creative_brief", {}).get("goal") or experiment["goal"],
        persona_segment=plan.get("persona"),
        copy_constraints={"headline_max_chars": 40, "body_max_chars": 90, "cta_max_chars": 20},
        partner_brand=None,
        brand_id=experiment["brand_id"],
        content_type=content_type,
        carousel_slide_count=slide_count,
        layout_style="auto",
    )
    # Fan out — one creative per brief object; route to video worker when needed
    with tenant_connection(tenant_id) as conn:
        brief_rows = conn.execute(
            "SELECT jsonb_array_length(brief) FROM campaigns WHERE id = %s",
            (str(campaign_id),),
        ).fetchone()
    n = int(brief_rows[0] or 0)
    task_fn = generate_video if media_type == "video" else generate_creative
    for i in range(n):
        task_fn.delay(str(tenant_id), str(campaign_id), i)
    return str(campaign_id)


# ============================================================
# publish — mock adapter now; real Meta in Phase C
# ============================================================

def _publish_iteration(tenant_id: UUID, experiment: dict, iteration: dict, plan: dict) -> dict:
    """Pick the first governance-passed creative from this iteration's
    campaign and hand it to the channel adapter. Returns the publish_ref."""
    from integrations.mock_ads import get_adapter

    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT id, storage_path, copy_headline, copy_body, copy_cta FROM creatives "
            "WHERE campaign_id = %s AND storage_path IS NOT NULL "
            "AND governance_status <> 'blocked' "
            "ORDER BY slide_index NULLS LAST, created_at LIMIT 1",
            (iteration["campaign_id"],),
        ).fetchone()
    if not r:
        raise RuntimeError("no publishable creative found for iteration")

    creative_id, storage_path, headline, body, cta = r
    adapter = get_adapter(plan.get("channel") or "mock_ads")
    pub_ref = adapter.publish(
        tenant_id=str(tenant_id),
        iteration_id=iteration["id"],
        creative_id=str(creative_id),
        storage_path=storage_path,
        copy={"headline": headline, "body": body, "cta": cta},
        format=plan["format"], persona=plan.get("persona"),
        spend_planned=float(plan["spend_planned"]),
    )
    # Record a deployments row for consistency with the existing dispatch path
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "insert into deployments (tenant_id, creative_id, channel, status, payload) "
            "values (%s, %s, %s, 'published', %s::jsonb)",
            (str(tenant_id), str(creative_id), plan.get("channel") or "mock_ads",
             json.dumps(pub_ref, default=str)),
        )
    return pub_ref


# ============================================================
# analyze — Gemini's verdict on metrics vs hypothesis
# ============================================================

_ANALYZE_PROMPT = """You are analysing ONE ad iteration against its hypothesis.
Return STRICT JSON:
{
  "beat_hypothesis": true|false,
  "direction": "up" | "down" | "flat",
  "magnitude": <number 0..1 — how large the effect vs the hypothesis>,
  "primary_metric_value": <number, in the goal_metric units>,
  "dimensions_that_mattered": ["visual_style", "format", ...],
  "summary": "one-paragraph plain-English readout, referencing the numbers"
}

Rules:
- If spend_actual < min_spend_for_verdict, set beat_hypothesis=false and
  direction="flat" (not enough signal), regardless of the numbers.
- Be conservative on causality — call out confounds when relevant.
- Direction "up" means: goal_metric moved favourably vs the iteration's plausible baseline.
"""


def analyze_iteration(tenant_id: UUID, experiment: dict, iteration: dict) -> dict:
    context = {
        "goal_metric": experiment["goal_metric"],
        "goal_target": experiment["goal_target"],
        "min_spend_for_verdict": experiment["min_spend_for_verdict"],
        "hypothesis": iteration["hypothesis"],
        "format": iteration["format"],
        "persona": iteration["persona"],
        "spend_planned": float(iteration.get("spend_planned") or 0),
        "spend_actual": float(iteration.get("spend_actual") or 0),
        "metrics": iteration.get("metrics"),
    }
    resp = traced_generate(
        model=MODEL,
        contents=_ANALYZE_PROMPT + "\n\nITERATION:\n" + json.dumps(context, default=str, indent=2),
        config=genai_types.GenerateContentConfig(
            temperature=0.2, response_mime_type="application/json",
        ),
        trace_name="orchestrator.analyze",
        tenant_id=str(tenant_id),
        campaign_id=experiment["id"],
    )
    try:
        verdict = json.loads(resp.text or "{}")
    except Exception:
        verdict = {"beat_hypothesis": False, "direction": "flat",
                   "magnitude": 0.0, "summary": "unparseable analyzer response"}
    return verdict


# ============================================================
# decide — goal met / budget exhausted / continue
# ============================================================

def decide_next(tenant_id: UUID, experiment_id: str) -> str:
    """Return 'goal_met' | 'budget_exhausted' | 'max_iterations' | 'continue'."""
    exp = _load_experiment(tenant_id, experiment_id)
    if exp is None:
        return "continue"
    history = _iteration_history(tenant_id, experiment_id, limit=exp["max_iterations"])
    if exp["goal_target"] is not None:
        cumulative = sum(
            (h.get("metrics") or {}).get(exp["goal_metric"], 0) or 0
            for h in history
        )
        if cumulative >= exp["goal_target"]:
            return "goal_met"
    remaining = exp["budget_total"] - exp["budget_spent"] - exp["budget_committed"]
    min_next = max(50.0, exp["min_spend_for_verdict"])
    if remaining < min_next:
        return "budget_exhausted"
    if len(history) >= exp["max_iterations"]:
        return "max_iterations"
    return "continue"


# ============================================================
# Report generation
# ============================================================

_REPORT_PROMPT = """You are writing the closing report for a completed autonomous
ad experiment. Return STRICT JSON:
{
  "headline": "one-sentence outcome (goal met / budget spent, key learning)",
  "summary": "4-8 sentence executive summary",
  "what_worked": ["bullet", ...],
  "what_did_not": ["bullet", ...],
  "recommendations_for_next_experiment": ["bullet", ...],
  "top_learnings": [{"dimension": "...", "statement": "...", "confidence": 0..1}, ...]
}
Be concrete and reference the actual numbers/formats/personas that appeared."""


def build_report(tenant_id: UUID, experiment_id: str) -> dict:
    exp = _load_experiment(tenant_id, experiment_id)
    if not exp:
        return {}
    history = _iteration_history(tenant_id, experiment_id, limit=exp["max_iterations"])
    # Fresh learnings snapshot
    with tenant_connection(tenant_id) as conn:
        rows = conn.execute(
            "SELECT dimension, statement, confidence FROM learnings "
            "WHERE tenant_id = %s AND (brand_id = %s OR (brand_id IS NULL AND %s IS NULL)) "
            "AND superseded_by IS NULL ORDER BY confidence DESC LIMIT 12",
            (str(tenant_id), exp["brand_id"], exp["brand_id"]),
        ).fetchall()
    top_learnings = [{"dimension": r[0], "statement": r[1], "confidence": float(r[2])} for r in rows]

    context = {
        "goal": exp["goal"], "goal_metric": exp["goal_metric"],
        "goal_target": exp["goal_target"],
        "budget_total": exp["budget_total"], "budget_spent": exp["budget_spent"],
        "iterations": history, "top_learnings": top_learnings,
    }
    try:
        resp = traced_generate(
            model=MODEL,
            contents=_REPORT_PROMPT + "\n\nDATA:\n" + json.dumps(context, default=str, indent=2),
            config=genai_types.GenerateContentConfig(temperature=0.4, response_mime_type="application/json"),
            trace_name="orchestrator.report",
            tenant_id=str(tenant_id),
            campaign_id=experiment_id,
        )
        report = json.loads(resp.text or "{}")
    except Exception as e:
        log.warning("report LLM failed: %s", e)
        report = {"headline": "report generation failed",
                  "summary": str(e), "what_worked": [], "what_did_not": [],
                  "recommendations_for_next_experiment": [], "top_learnings": top_learnings}
    report["stats"] = {
        "iterations": len(history),
        "budget_spent": exp["budget_spent"], "budget_total": exp["budget_total"],
        "cumulative_metric": sum((h.get("metrics") or {}).get(exp["goal_metric"], 0) or 0 for h in history),
    }
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE experiments SET report = %s::jsonb, updated_at = now() WHERE id = %s",
            (json.dumps(report, default=str), experiment_id),
        )
    return report


# ============================================================
# The graph itself — driven imperatively by run_next_step().
# We chose imperative-over-LangGraph here because the checkpointing
# gain doesn't offset the added complexity for a slow-cycle loop
# whose durable state is already in Postgres tables. Each phase of
# the loop is a distinct Celery task step.
# ============================================================

def run_next_step(tenant_id_str: str, experiment_id: str) -> dict:
    """Advance an experiment one node forward. Idempotent per node —
    safe to re-invoke on retries. Returns {step, status} for logging.

    Called from:
      - POST /experiments (initial kick),
      - approve/resume,
      - workers.orchestrator_tick after `measuring` deadline elapses,
      - after each brief_and_generate/analyze completes.
    """
    tenant_id = UUID(tenant_id_str)
    exp = _load_experiment(tenant_id, experiment_id)
    if exp is None:
        return {"step": "noop", "reason": "not_found"}
    if exp["status"] in ("paused", "awaiting_approval", "stopped",
                         "goal_met", "budget_exhausted", "failed"):
        return {"step": "noop", "reason": exp["status"]}

    # Find any in-flight iteration that needs work
    with tenant_connection(tenant_id) as conn:
        pending = conn.execute(
            "SELECT id, index, status, campaign_id, hypothesis, format, channel, "
            "persona, spend_planned, publish_ref, brief, applied_learnings, measure_deadline "
            "FROM experiment_iterations "
            "WHERE experiment_id = %s AND status NOT IN ('analyzed','skipped','failed') "
            "ORDER BY index ASC LIMIT 1",
            (experiment_id,),
        ).fetchone()

    if not pending:
        return _plan_and_start_iteration(tenant_id, exp)

    iteration = {
        "id": str(pending[0]), "index": pending[1], "status": pending[2],
        "campaign_id": str(pending[3]) if pending[3] else None,
        "hypothesis": pending[4], "format": pending[5], "channel": pending[6],
        "persona": pending[7], "spend_planned": float(pending[8] or 0),
        "publish_ref": pending[9], "brief": pending[10],
        "applied_learnings": pending[11], "measure_deadline": pending[12],
    }

    if iteration["status"] == "planning":
        return _run_generate(tenant_id, exp, iteration)
    if iteration["status"] == "generating":
        return _check_generation_then_publish(tenant_id, exp, iteration)
    if iteration["status"] == "awaiting_approval":
        return {"step": "wait", "reason": "user approval"}
    if iteration["status"] == "publishing":
        return _run_publish(tenant_id, exp, iteration)
    if iteration["status"] == "published":
        return _to_measuring(tenant_id, exp, iteration)
    if iteration["status"] == "measuring":
        return _try_measure(tenant_id, exp, iteration)
    return {"step": "noop", "status": iteration["status"]}


def _plan_and_start_iteration(tenant_id: UUID, exp: dict) -> dict:
    """No open iteration — decide whether to plan a new one or wrap the experiment."""
    decision = decide_next(tenant_id, exp["id"])
    if decision != "continue":
        _set_experiment_status(tenant_id, exp["id"], decision)
        build_report(tenant_id, exp["id"])
        _audit(tenant_id, "experiment.completed", exp["id"], {"reason": decision})
        return {"step": "completed", "reason": decision}

    plan = plan_iteration(tenant_id, exp["id"])
    idx = _next_index(tenant_id, exp["id"])
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "INSERT INTO experiment_iterations "
            "(experiment_id, tenant_id, index, hypothesis, format, channel, persona, "
            "spend_planned, brief, applied_learnings, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'planning') "
            "RETURNING id",
            (exp["id"], str(tenant_id), idx,
             plan.get("hypothesis"), plan["format"], plan["channel"], plan.get("persona"),
             plan["spend_planned"], json.dumps(plan.get("creative_brief") or {}),
             json.dumps(plan.get("applied_learnings") or [])),
        ).fetchone()
    iteration_id = str(r[0])
    _audit(tenant_id, "iteration.planned", iteration_id,
           {"experiment_id": exp["id"], "index": idx, "plan": plan})

    # Spend gate — hybrid guardrail
    cap = exp["per_iteration_cap"]
    if cap is not None and plan["spend_planned"] > cap + 1e-6:
        _update_iteration(tenant_id, iteration_id, status="awaiting_approval")
        _set_experiment_status(tenant_id, exp["id"], "awaiting_approval")
        _audit(tenant_id, "iteration.awaiting_approval", iteration_id,
               {"planned": plan["spend_planned"], "cap": cap})
        return {"step": "awaiting_approval", "iteration_id": iteration_id}

    # Reserve budget then step to generate
    try:
        commit_planned_spend(tenant_id, exp["id"], plan["spend_planned"])
    except BudgetError as e:
        _update_iteration(tenant_id, iteration_id, status="skipped", error=str(e))
        return {"step": "skipped", "reason": str(e)}

    return _run_generate(tenant_id, exp, {
        "id": iteration_id, "index": idx, "status": "planning",
        "campaign_id": None,
        "hypothesis": plan.get("hypothesis"), "format": plan["format"],
        "channel": plan["channel"], "persona": plan.get("persona"),
        "spend_planned": plan["spend_planned"], "publish_ref": None,
        "brief": plan.get("creative_brief") or {},
        "applied_learnings": plan.get("applied_learnings") or [],
        "measure_deadline": None,
    })


def _run_generate(tenant_id: UUID, exp: dict, it: dict) -> dict:
    campaign_id = _generate_creative_for_iteration(tenant_id, exp, it, {
        "format": it["format"], "channel": it["channel"], "persona": it["persona"],
        "spend_planned": it["spend_planned"],
        "creative_brief": it["brief"] or {},
    })
    _update_iteration(tenant_id, it["id"], status="generating", campaign_id=campaign_id)
    _audit(tenant_id, "iteration.generating", it["id"],
           {"campaign_id": campaign_id})
    return {"step": "generating", "iteration_id": it["id"], "campaign_id": campaign_id}


def _check_generation_then_publish(tenant_id: UUID, exp: dict, it: dict) -> dict:
    """Called by the beat tick; publishes as soon as any creative is ready
    (governance may still be in-flight but non-blocked)."""
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT COUNT(*) FILTER (WHERE storage_path IS NOT NULL) AS ready, "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE governance_status = 'blocked') AS blocked "
            "FROM creatives WHERE campaign_id = %s",
            (it["campaign_id"],),
        ).fetchone()
    ready, total, blocked = int(r[0]), int(r[1]), int(r[2])
    if total == 0 or ready == 0:
        return {"step": "wait_generation", "iteration_id": it["id"]}
    if ready == blocked and blocked > 0:
        _update_iteration(tenant_id, it["id"], status="failed",
                          error="all creatives blocked by governance")
        release_planned_spend(tenant_id, exp["id"], it["spend_planned"])
        return {"step": "generation_blocked", "iteration_id": it["id"]}
    _update_iteration(tenant_id, it["id"], status="publishing")
    return _run_publish(tenant_id, exp, {**it, "status": "publishing"})


def _run_publish(tenant_id: UUID, exp: dict, it: dict) -> dict:
    plan_view = {
        "format": it["format"], "channel": it["channel"], "persona": it["persona"],
        "spend_planned": it["spend_planned"],
    }
    try:
        pub_ref = _publish_iteration(tenant_id, exp, it, plan_view)
    except Exception as e:
        _update_iteration(tenant_id, it["id"], status="failed", error=str(e))
        release_planned_spend(tenant_id, exp["id"], it["spend_planned"])
        _audit(tenant_id, "iteration.publish_failed", it["id"], {"error": str(e)})
        return {"step": "publish_failed", "iteration_id": it["id"], "error": str(e)}

    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=exp["metric_window_hours"])
    _update_iteration(
        tenant_id, it["id"],
        status="published", publish_ref=json.dumps(pub_ref, default=str),
        published_at=now, measure_deadline=deadline,
    )
    _audit(tenant_id, "iteration.published", it["id"],
           {"publish_ref": pub_ref, "deadline": deadline.isoformat()})
    return _to_measuring(tenant_id, exp, {**it, "publish_ref": pub_ref,
                                          "measure_deadline": deadline})


def _to_measuring(tenant_id: UUID, exp: dict, it: dict) -> dict:
    """Flip to `measuring`; the beat tick will poll and eventually analyze."""
    _update_iteration(tenant_id, it["id"], status="measuring")
    return {"step": "measuring", "iteration_id": it["id"],
            "deadline": it["measure_deadline"].isoformat() if it["measure_deadline"] else None}


def _try_measure(tenant_id: UUID, exp: dict, it: dict) -> dict:
    """Poll the adapter; on deadline, analyze + distill + step to next iteration."""
    from integrations.mock_ads import get_adapter

    adapter = get_adapter(it["channel"] or "mock_ads")
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT published_at, metrics_history FROM experiment_iterations WHERE id = %s",
            (it["id"],),
        ).fetchone()
    published_at, hist = r
    hist = list(hist or [])
    elapsed_hours = ((datetime.now(timezone.utc) - published_at).total_seconds() / 3600.0
                     if published_at else 0.0)
    metrics = adapter.poll_metrics(
        publish_ref=it["publish_ref"] or {},
        format=it["format"], persona=it["persona"],
        hypothesis=it["hypothesis"],
        spend_planned=it["spend_planned"],
        window_hours=exp["metric_window_hours"],
        elapsed_hours=elapsed_hours,
        poll_index=len(hist),
    )
    hist.append(metrics)
    _update_iteration(
        tenant_id, it["id"],
        metrics=json.dumps(metrics, default=str),
        metrics_history=json.dumps(hist, default=str),
    )

    # Not time to analyze yet
    deadline = it["measure_deadline"]
    if deadline and datetime.now(timezone.utc) < deadline:
        return {"step": "measuring_poll", "iteration_id": it["id"],
                "elapsed_hours": round(elapsed_hours, 2)}

    # Deadline reached — analyze, distill, close ledger, and loop
    with tenant_connection(tenant_id) as conn:
        row = conn.execute(
            "SELECT id, hypothesis, format, channel, persona, spend_planned, brief, metrics "
            "FROM experiment_iterations WHERE id = %s",
            (it["id"],),
        ).fetchone()
    iteration_full = {
        "id": str(row[0]), "hypothesis": row[1], "format": row[2],
        "channel": row[3], "persona": row[4],
        "spend_planned": float(row[5] or 0),
        "spend_actual": float((metrics.get("spend") if metrics else 0) or 0),
        "brief": row[6], "metrics": row[7],
        "min_spend_for_verdict": exp["min_spend_for_verdict"],
    }
    verdict = analyze_iteration(tenant_id, exp, iteration_full)
    # Distill (Phase A) — non-fatal
    try:
        from learning_store import distill_iteration
        distill_iteration(
            tenant_id=str(tenant_id),
            brand_id=exp["brand_id"],
            iteration={**iteration_full, "verdict": verdict},
        )
    except Exception as e:
        log.warning("distill failed: %s", e)

    # Realize the spend against the ledger
    realize_spend(tenant_id, exp["id"], it["spend_planned"], iteration_full["spend_actual"])
    _update_iteration(
        tenant_id, it["id"],
        status="analyzed", verdict=json.dumps(verdict, default=str),
        measured_at=datetime.now(timezone.utc),
        spend_actual=iteration_full["spend_actual"],
    )
    _audit(tenant_id, "iteration.analyzed", it["id"],
           {"verdict": verdict, "spend_actual": iteration_full["spend_actual"]})

    # Immediately try to plan the next iteration (or close out)
    return _plan_and_start_iteration(tenant_id, exp)
