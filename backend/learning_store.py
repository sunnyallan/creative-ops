"""v4.0 Phase A — Learning store: distill iterations into embedding-indexed
learnings; retrieve top-k relevant learnings to inject into future briefs.

The store is what makes the orchestrator get *smarter* over time. Every
iteration's (hypothesis, metrics, verdict) becomes zero or more learnings
scoped to the brand. Similar learnings are corroborated (confidence ↑) or
contradicted (confidence ↓); truly new ones are inserted. Retrieval uses
pgvector cosine similarity over the same embedding space, filtered by
brand + confidence floor.

Model choice:
  Embeddings — gemini-embedding-001 (768-d), matches migration 011 column.
  Distillation + retrieval-context — gemini-2.5-flash (same as briefing).
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from google.genai import types as genai_types

from db.session import tenant_connection
from observability import gemini_client, traced_generate

log = logging.getLogger("learning_store")

EMBEDDING_MODEL = "gemini-embedding-001"
DISTILL_MODEL = "gemini-2.5-flash"
EMBEDDING_DIM = 768

# Similarity threshold above which we treat a candidate learning as
# "the same as" an existing one → corroborate/contradict instead of insert.
_DEDUP_SIM_THRESHOLD = 0.86
_MIN_CONFIDENCE_FLOOR = 0.15

# Dimensions the distiller is allowed to emit. Kept in sync with migration 011.
_DIMENSIONS = {
    "visual_style", "copy_angle", "format", "persona",
    "channel", "timing", "tags", "audience", "cta",
}


# ============================================================
# Embeddings
# ============================================================

def _embed(text: str) -> list[float] | None:
    """Return a 768-d embedding for `text`, or None on failure (non-fatal)."""
    if not text or not text.strip():
        return None
    try:
        client = gemini_client()
        resp = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=genai_types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
        )
        # SDK shape: resp.embeddings[0].values
        embs = getattr(resp, "embeddings", None) or []
        if not embs:
            return None
        values = getattr(embs[0], "values", None)
        return list(values) if values else None
    except Exception as e:
        log.warning("embedding failed: %s", e)
        return None


def _to_pgvector(values: list[float]) -> str:
    """pgvector accepts a bracketed float list as a string literal."""
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


# ============================================================
# Distillation — Gemini turns an iteration outcome into learning candidates
# ============================================================

_DISTILL_PROMPT = """You are a growth-marketing analyst reviewing ONE ad iteration.
Extract 0-4 CRISP, GENERALISABLE learnings from what happened.

RULES for good learnings:
- Statement must be actionable in future briefs, not just descriptive.
- Include the DIRECTION of the effect and (when known) rough magnitude.
- Attach the correct DIMENSION from this allowed list: visual_style, copy_angle,
  format, persona, channel, timing, tags, audience, cta.
- Confidence 0.4-0.7 for single-iteration signal; higher only if effect is dramatic
  AND spend/impressions crossed the min viable threshold.
- If the iteration is inconclusive (below min spend, no significant delta, ambiguous
  result), return NO learnings. Do NOT invent.
- Do NOT restate the brief. State what we learned about what works or does not.

Return STRICT JSON: {"learnings": [{"dimension": "...", "statement": "...", "confidence": 0.55}, ...]}
"""


def distill_iteration(
    *,
    tenant_id: str,
    brand_id: str | None,
    iteration: dict[str, Any],
) -> list[dict]:
    """Run the distiller for one iteration; upsert learnings into the store.

    `iteration` is expected to contain:
      hypothesis, brief, format, channel, persona, metrics, verdict,
      spend_actual, min_spend_for_verdict (from parent experiment).

    Returns the list of learnings that were upserted (with `action`:
    'inserted' | 'corroborated' | 'contradicted' | 'skipped_low_confidence').
    """
    context = {
        "hypothesis": iteration.get("hypothesis"),
        "brief_summary": {
            "goal": (iteration.get("brief") or {}).get("goal"),
            "format": iteration.get("format"),
            "channel": iteration.get("channel"),
            "persona": iteration.get("persona"),
            "headline": (iteration.get("brief") or {}).get("headline"),
            "image_direction": (iteration.get("brief") or {}).get("image_direction"),
        },
        "spend_actual": iteration.get("spend_actual"),
        "min_spend_for_verdict": iteration.get("min_spend_for_verdict"),
        "metrics": iteration.get("metrics"),
        "verdict": iteration.get("verdict"),
    }

    prompt = _DISTILL_PROMPT + "\n\nITERATION:\n" + json.dumps(context, default=str, indent=2)
    try:
        resp = traced_generate(
            model=DISTILL_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
            trace_name="learning_store.distill",
            tenant_id=tenant_id,
        )
        parsed = json.loads(resp.text or "{}")
    except Exception as e:
        log.warning("distill LLM call failed: %s", e)
        return []

    candidates = parsed.get("learnings") or []
    results: list[dict] = []
    for c in candidates:
        dim = str(c.get("dimension", "")).strip().lower()
        stmt = str(c.get("statement", "")).strip()
        conf = float(c.get("confidence", 0.5) or 0.5)
        if dim not in _DIMENSIONS or not stmt:
            continue
        if conf < _MIN_CONFIDENCE_FLOOR:
            results.append({"action": "skipped_low_confidence", "statement": stmt})
            continue
        action = _upsert_learning(
            tenant_id=tenant_id,
            brand_id=brand_id,
            dimension=dim,
            statement=stmt,
            confidence=conf,
            iteration_id=iteration.get("id"),
            metric_snapshot=iteration.get("metrics"),
            verdict_direction=(iteration.get("verdict") or {}).get("direction"),
        )
        results.append({"action": action, "dimension": dim, "statement": stmt, "confidence": conf})
    return results


def _upsert_learning(
    *,
    tenant_id: str,
    brand_id: str | None,
    dimension: str,
    statement: str,
    confidence: float,
    iteration_id: str | None,
    metric_snapshot: Any,
    verdict_direction: str | None,   # 'up' | 'down' | None
) -> str:
    """Insert a new learning, or corroborate/contradict a near-duplicate.

    Returns action taken: 'inserted' | 'corroborated' | 'contradicted' | 'skipped_no_embedding'.
    """
    vec = _embed(f"[{dimension}] {statement}")
    if vec is None:
        return "skipped_no_embedding"
    vec_lit = _to_pgvector(vec)

    evidence_entry = {
        "iteration_id": str(iteration_id) if iteration_id else None,
        "metric": metric_snapshot,
        "direction": verdict_direction,
    }

    with tenant_connection(UUID(tenant_id)) as conn:
        # Look for a same-dimension, same-brand near-duplicate.
        neighbour = conn.execute(
            "SELECT id, statement, confidence, evidence, "
            "1 - (embedding <=> %s::vector) AS sim "
            "FROM learnings WHERE tenant_id = %s AND dimension = %s "
            "AND (brand_id = %s OR (brand_id IS NULL AND %s IS NULL)) "
            "AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT 1",
            (vec_lit, tenant_id, dimension, brand_id, brand_id, vec_lit),
        ).fetchone()

        if neighbour and float(neighbour[4] or 0) >= _DEDUP_SIM_THRESHOLD:
            existing_id, _stmt, existing_conf, existing_ev, sim = neighbour
            same_direction = (verdict_direction or "up") == "up"
            # Bayesian-ish update: nudge toward 1 on corroborate, toward 0 on contradict.
            step = 0.08 * confidence
            new_conf = float(existing_conf) + (step if same_direction else -step)
            new_conf = max(0.05, min(0.99, new_conf))
            ev = list(existing_ev or [])
            ev.append(evidence_entry)
            conn.execute(
                "UPDATE learnings SET confidence = %s, evidence = %s::jsonb, "
                "last_validated_at = now(), updated_at = now() WHERE id = %s",
                (new_conf, json.dumps(ev, default=str), str(existing_id)),
            )
            return "corroborated" if same_direction else "contradicted"

        conn.execute(
            "INSERT INTO learnings (tenant_id, brand_id, dimension, statement, "
            "confidence, evidence, embedding, last_validated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector, now())",
            (tenant_id, brand_id, dimension, statement, confidence,
             json.dumps([evidence_entry], default=str), vec_lit),
        )
        return "inserted"


# ============================================================
# Retrieval — top-k learnings relevant to a briefing context
# ============================================================

def retrieve_for_brief(
    *,
    tenant_id: str,
    brand_id: str | None,
    context: str,
    k: int = 8,
    min_confidence: float = 0.35,
) -> list[dict]:
    """Return up to k learnings ranked by cosine similarity to `context`,
    scoped to the brand and filtered by a confidence floor."""
    vec = _embed(context)
    if vec is None:
        # Fall back to highest-confidence recent learnings for the brand.
        with tenant_connection(UUID(tenant_id)) as conn:
            rows = conn.execute(
                "SELECT id, dimension, statement, confidence, times_applied "
                "FROM learnings WHERE tenant_id = %s "
                "AND (brand_id = %s OR (brand_id IS NULL AND %s IS NULL)) "
                "AND confidence >= %s AND superseded_by IS NULL "
                "ORDER BY confidence DESC, updated_at DESC LIMIT %s",
                (tenant_id, brand_id, brand_id, min_confidence, k),
            ).fetchall()
        return [_row_to_learning(r) for r in rows]

    vec_lit = _to_pgvector(vec)
    with tenant_connection(UUID(tenant_id)) as conn:
        rows = conn.execute(
            "SELECT id, dimension, statement, confidence, times_applied, "
            "1 - (embedding <=> %s::vector) AS sim "
            "FROM learnings WHERE tenant_id = %s "
            "AND (brand_id = %s OR (brand_id IS NULL AND %s IS NULL)) "
            "AND embedding IS NOT NULL AND confidence >= %s "
            "AND superseded_by IS NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (vec_lit, tenant_id, brand_id, brand_id, min_confidence, vec_lit, k),
        ).fetchall()
    return [_row_to_learning(r) for r in rows]


def _row_to_learning(r: tuple) -> dict:
    return {
        "id": str(r[0]),
        "dimension": r[1],
        "statement": r[2],
        "confidence": float(r[3]),
        "times_applied": int(r[4] or 0),
        "similarity": float(r[5]) if len(r) > 5 else None,
    }


def mark_applied(tenant_id: str, learning_ids: list[str]) -> None:
    """Bump times_applied when the briefing agent uses these learnings."""
    if not learning_ids:
        return
    with tenant_connection(UUID(tenant_id)) as conn:
        conn.execute(
            "UPDATE learnings SET times_applied = times_applied + 1 "
            "WHERE tenant_id = %s AND id = ANY(%s::uuid[])",
            (tenant_id, learning_ids),
        )


# ============================================================
# Prompt block — the injection format shared with the briefing agent
# ============================================================

def learnings_prompt_block(learnings: list[dict]) -> str:
    """Formatted PROVEN LEARNINGS block. Empty string when no learnings —
    keeps the calling prompt clean on first-ever runs."""
    if not learnings:
        return ""
    lines = ["=== PROVEN LEARNINGS FOR THIS BRAND (from prior autonomous experiments) ==="]
    lines.append("Treat these as strong priors. Deviate only when the current goal genuinely conflicts.")
    for l in learnings:
        conf_pct = int(round(l["confidence"] * 100))
        applied = f" ×{l['times_applied']}" if l.get("times_applied") else ""
        lines.append(f"- [{l['dimension']} · {conf_pct}%{applied}] {l['statement']}")
    lines.append("=== END LEARNINGS ===\n")
    return "\n".join(lines)
