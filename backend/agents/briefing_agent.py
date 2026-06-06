"""LangGraph briefing agent.

Subsystem 2 — Intelligence Engine.

Nodes: read_brand_kit → analyse_persona → generate_brief → output_brief
- Brand kit JSON is placed at the START of every Gemini prompt to maximise
  implicit caching (90% discount on cached prefix tokens for Gemini 3.x).
- Persistence: PostgresSaver against Supabase Postgres so beta users can
  pause/resume mid-flow.
- Qdrant similarity check (deduplication) is wired as a no-op for MVP;
  swap in when Qdrant is online (Phase 2 of the doc).
"""
from __future__ import annotations

import json
from typing import Any, TypedDict
from uuid import UUID

from google import genai
from google.genai import types as genai_types
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.postgres import PostgresSaver

from config import settings
from db.session import tenant_connection
from observability import traced_generate

MODEL_PRO = "gemini-2.5-flash"
MODEL_FLASH_LITE = "gemini-2.5-flash-lite"


class BriefingState(TypedDict, total=False):
    tenant_id: str
    campaign_id: str
    campaign_goal: str
    persona_segment: str | None
    copy_constraints: dict[str, int]
    partner_brand: dict[str, Any] | None
    brand_kit: dict[str, Any]
    existing_similar: list[dict[str, Any]]
    output_brief: list[dict[str, Any]]


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def read_brand_kit(state: BriefingState) -> BriefingState:
    tenant_id = UUID(state["tenant_id"])
    with tenant_connection(tenant_id) as conn:
        cur = conn.execute(
            "SELECT brand_name, tone, values, colours, fonts, logo_paths, persona_definitions "
            "FROM brand_kits WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
            (str(tenant_id),),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError("brand kit not found — complete onboarding first")
    brand_kit = {
        "brand_name": row[0], "tone": row[1], "values": row[2],
        "colours": row[3], "fonts": row[4], "logo_paths": row[5],
        "persona_definitions": row[6],
    }
    return {**state, "brand_kit": brand_kit}


def analyse_persona(state: BriefingState) -> BriefingState:
    """Pick the persona segment (use provided, else first defined)."""
    requested = state.get("persona_segment")
    personas = state["brand_kit"].get("persona_definitions") or []
    if requested:
        chosen = next((p for p in personas if p.get("name") == requested), None)
    else:
        chosen = personas[0] if personas else None
    if not chosen:
        chosen = {"name": "general", "lifestyle": "broad audience"}
    return {**state, "persona_segment": chosen["name"], "brand_kit": {**state["brand_kit"], "_active_persona": chosen}}


def _brand_prefix(brand_kit: dict[str, Any]) -> str:
    """Stable, cache-friendly prefix — brand kit JSON first, then instructions."""
    return (
        "<BRAND_KIT>\n"
        + json.dumps(brand_kit, indent=2, ensure_ascii=False)
        + "\n</BRAND_KIT>\n\n"
        "You are the Intelligence Engine of an AI creative-ops platform. "
        "Stay strictly on-brand. Output only valid JSON when asked.\n"
    )


def generate_brief(state: BriefingState) -> BriefingState:
    brand_kit = state["brand_kit"]
    persona = brand_kit.get("_active_persona") or {"name": state.get("persona_segment", "general")}
    goal = state["campaign_goal"]

    # Pull channels from tenant config (with built-in defaults merged in)
    from api.channels import active_channels_for
    channels = active_channels_for(UUID(state["tenant_id"]))

    constraints = state.get("copy_constraints") or {
        "headline_max_chars": 30, "body_max_chars": 50, "cta_max_chars": 15,
    }

    channels_block = json.dumps(channels, indent=2)

    partner_block = ""
    partner: dict | None = state.get("partner_brand")  # type: ignore
    if partner:
        partner_name_str = partner.get("name", "")
        products_str = (partner.get("products_or_services") or "").strip()
        if products_str:
            product_anchor = (
                f"PARTNER ACTUALLY SELLS: {products_str}.\n"
                f"The hero object in image_direction MUST be ONE of these products. "
                f"Do NOT default to general 'category' objects (travel gear, fitness equipment, etc) — "
                f"only what the partner literally transacts.\n"
            )
        else:
            product_anchor = (
                f"Identify what '{partner_name_str}' actually transacts as products "
                f"(e.g. Cleartrip transacts: flights, hotels, trains, buses, NOT travel gear; "
                f"Zomato transacts: food orders, NOT cooking equipment).\n"
            )
        partner_block = (
            f"\nPARTNERSHIP: This is a co-branded offer with '{partner_name_str}'.\n"
            f"{product_anchor}\n"
            f"STEP 1 — Frame copy as a partnership ('with', 'x', 'at'). Mention partner brand name.\n"
            f"STEP 2 — image_direction hero object MUST be the partner's actual transactable product. "
            f"Persona changes the CONTEXT/STYLING, not the object type:\n"
            f"  • Cleartrip × Fitness Buffs → hotel room with gym view / boarding pass + sports kit / "
            f"a wellness-resort hotel key — but always a TRAVEL transaction object\n"
            f"  • Cleartrip × Empty Nesters → boutique hotel suite, premium boarding pass, leather carry-on\n"
            f"  • Cleartrip × Families → family flight tickets, hotel pool with kids, group boarding passes\n"
            f"  • Zomato × Eco-Conscious → plant-forward meal in a compostable box, but still a FOOD delivery\n"
            f"NEVER substitute the object with something from the persona's primary lifestyle that the "
            f"partner doesn't sell. NEVER suggest credit card, debit card, wallet, or payment-card imagery.\n"
        )

    prompt = (
        _brand_prefix(brand_kit)
        + "TASK: Produce a structured creative brief as a JSON array. "
        "One object per channel in CHANNELS. Each object must have: "
        "channel, dimensions, copy_brief, persona_segment, tone, image_direction, cta.\n"
        f"Respect copy length limits — headline ≤ {constraints['headline_max_chars']} chars, "
        f"body ≤ {constraints['body_max_chars']} chars, cta ≤ {constraints['cta_max_chars']} chars.\n\n"
        "IMPORTANT — TAILOR image_direction TO THE PERSONA:\n"
        "• High-income / premium personas → aspirational, fine-dining / boutique / wellness-spa / luxury-travel context\n"
        "• Mid-income / mass-market personas → relatable everyday context (street food, casual dining, family grocery, gym)\n"
        "• Gen Z / student personas → bold colours, trending objects, social-media-ready\n"
        "• New parents → warm, soft, family-oriented objects\n"
        "Pick a hero object that's specifically right for THIS persona's income tier and lifestyle.\n"
        f"{partner_block}\n"
        f"CAMPAIGN_GOAL: {goal}\n\n"
        f"PERSONA: {json.dumps(persona)}\n\n"
        f"CHANNELS:\n{channels_block}\n\n"
        "Return ONLY the JSON array."
    )

    resp = traced_generate(
        model=MODEL_PRO,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
        trace_name="briefing.generate_brief",
        tenant_id=state["tenant_id"],
        campaign_id=state["campaign_id"],
        metadata={"persona": state.get("persona_segment"), "goal": goal[:200]},
    )
    briefs = json.loads(resp.text)
    if not isinstance(briefs, list):
        raise ValueError("brief must be a JSON array")
    return {**state, "output_brief": briefs}


def persist_brief(state: BriefingState) -> BriefingState:
    """Persist brief to campaigns.brief."""
    tenant_id = UUID(state["tenant_id"])
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE campaigns SET brief = %s::jsonb, status = 'briefed' WHERE id = %s AND tenant_id = %s",
            (json.dumps(state["output_brief"]), state["campaign_id"], str(tenant_id)),
        )
    return state


def build_graph():
    g = StateGraph(BriefingState)
    g.add_node("read_brand_kit", read_brand_kit)
    g.add_node("analyse_persona", analyse_persona)
    g.add_node("generate_brief", generate_brief)
    g.add_node("persist_brief", persist_brief)
    g.set_entry_point("read_brand_kit")
    g.add_edge("read_brand_kit", "analyse_persona")
    g.add_edge("analyse_persona", "generate_brief")
    g.add_edge("generate_brief", "persist_brief")
    g.add_edge("persist_brief", END)
    return g


def run_briefing(
    tenant_id: UUID,
    campaign_id: UUID,
    goal: str,
    persona_segment: str | None,
    copy_constraints: dict[str, int] | None = None,
    partner_brand: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Synchronous helper invoked from API or Celery task."""
    with PostgresSaver.from_conn_string(settings.supabase_db_url) as saver:
        saver.setup()
        graph = build_graph().compile(checkpointer=saver)
        thread = {"configurable": {"thread_id": f"campaign:{campaign_id}"}}
        result = graph.invoke(
            {
                "tenant_id": str(tenant_id),
                "campaign_id": str(campaign_id),
                "campaign_goal": goal,
                "persona_segment": persona_segment,
                "copy_constraints": copy_constraints or {
                    "headline_max_chars": 30,
                    "body_max_chars": 50,
                    "cta_max_chars": 15,
                },
                "partner_brand": partner_brand,
            },
            config=thread,
        )
        return result["output_brief"]
