"""Topic research using Gemini with Google search grounding.

Called before briefing when campaign.research_topic is set. Output is stored
on campaign.research_notes and consumed by the briefing agent.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from workers.celery_app import celery_app

MODEL = "gemini-2.5-flash"  # cheap + supports tools

RESEARCH_PROMPT = (
    "You are a marketing strategist preparing notes for a creative team. "
    "Research the topic below from a brand-marketing perspective.\n\n"
    "Use search where useful to find:\n"
    "• Current factual context (recent stats, trends, news from the past 12 months)\n"
    "• Common pain points, questions, or misconceptions consumers have about the topic\n"
    "• Hooks, framings, or angles that perform well on social\n"
    "• Notable comparisons, do's/don'ts, or actionable tips\n\n"
    "Produce 250–400 words of crisp, marketing-ready notes. No headings, no bullets — "
    "flowing prose paragraphs. End with one suggested 'editorial angle' the team could "
    "take when writing copy. Do NOT mention sources by name; just synthesise the facts.\n\n"
    "TOPIC: {topic}\n"
    "BRAND CONTEXT (tone, audience): {brand_context}\n"
)


@celery_app.task(name="research.gather")
def gather_research(tenant_id: str, campaign_id: str) -> dict:
    from google import genai
    from google.genai import types as genai_types

    from config import settings
    from db.session import tenant_connection

    t_uuid = UUID(tenant_id)
    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "SELECT research_topic, brand_id FROM campaigns WHERE id = %s AND tenant_id = %s",
            (campaign_id, str(t_uuid)),
        ).fetchone()
        if not row or not row[0]:
            return {"ok": False, "reason": "no research_topic"}
        topic = row[0]
        brand_id = row[1]

        # Brand context for tone/audience
        brand_ctx = "general"
        if brand_id:
            b = conn.execute(
                "SELECT name, tone, brand_values, brand_feel FROM brands WHERE id = %s",
                (str(brand_id),),
            ).fetchone()
            if b:
                bits = [f"brand: {b[0]}"]
                if b[1]: bits.append(f"tone: {b[1]}")
                if b[2]: bits.append(f"values: {b[2]}")
                if b[3]: bits.append(f"feel: {b[3]}")
                brand_ctx = "; ".join(bits)

    prompt = RESEARCH_PROMPT.format(topic=topic, brand_context=brand_ctx)

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                tools=[genai_types.Tool(google_search_retrieval=genai_types.GoogleSearchRetrieval())],
                temperature=0.5,
            ),
        )
        notes = (resp.text or "").strip()
        if not notes:
            raise ValueError("empty research response")
    except Exception as e:
        # Fallback — no grounding, just text completion
        try:
            client = genai.Client(api_key=settings.gemini_api_key)
            resp = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(temperature=0.5),
            )
            notes = (resp.text or "").strip()
        except Exception as e2:
            return {"ok": False, "reason": f"research failed: {e2}"}

    with tenant_connection(t_uuid) as conn:
        conn.execute(
            "UPDATE campaigns SET research_notes = %s WHERE id = %s",
            (notes, campaign_id),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s)",
            (str(t_uuid), "campaign.research_done", "campaign", campaign_id),
        )

    return {"ok": True, "char_count": len(notes)}
