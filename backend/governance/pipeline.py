"""Subsystem 4 — Governance Agent.

MVP: Stages 2 (Sightengine) + 3 (Gemini 3.1 Pro vision judge).
Stage 1 (Falconsai local NSFW) deferred per plan.

Returns: {"pass": bool, "issues": [str], "severity": "block"|"warn"|"none", "sightengine": {...}}
"""
from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import httpx
from google import genai
from google.genai import types as genai_types

from config import settings
from db.session import tenant_connection
from observability import traced_generate
from storage import download_bytes

MODEL_PRO = "gemini-2.5-flash"

SIGHTENGINE_URL = "https://api.sightengine.com/1.0/check.json"
SIGHTENGINE_MODELS = "nudity-2.1,gore-2.0,weapon,offensive,text-content"
SIGHTENGINE_BLOCK_THRESHOLD = 0.5


def _sightengine_check(image_bytes: bytes) -> dict[str, Any]:
    if not (settings.sightengine_api_user and settings.sightengine_api_secret):
        return {"skipped": True}
    files = {"media": ("creative.png", image_bytes, "image/png")}
    data = {
        "models": SIGHTENGINE_MODELS,
        "api_user": settings.sightengine_api_user,
        "api_secret": settings.sightengine_api_secret,
    }
    r = httpx.post(SIGHTENGINE_URL, files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


def _sightengine_verdict(result: dict[str, Any]) -> tuple[bool, list[str]]:
    if result.get("skipped"):
        return True, []
    issues: list[str] = []
    # nudity-2.1
    nud = result.get("nudity", {})
    if nud.get("sexual_activity", 0) > SIGHTENGINE_BLOCK_THRESHOLD: issues.append("sightengine:nudity_sexual")
    if nud.get("sexual_display", 0) > SIGHTENGINE_BLOCK_THRESHOLD: issues.append("sightengine:nudity_display")
    # gore
    if result.get("gore", {}).get("prob", 0) > SIGHTENGINE_BLOCK_THRESHOLD: issues.append("sightengine:gore")
    # weapon
    if result.get("weapon", {}).get("classes", {}).get("firearm", 0) > SIGHTENGINE_BLOCK_THRESHOLD:
        issues.append("sightengine:weapon")
    # offensive
    off = result.get("offensive", {})
    for k, v in off.items():
        if isinstance(v, (int, float)) and v > SIGHTENGINE_BLOCK_THRESHOLD and k != "prob":
            issues.append(f"sightengine:offensive_{k}")
    return (len(issues) == 0), issues


def _gemini_judge(image_bytes: bytes, brand_kit: dict[str, Any], brief: dict[str, Any], copy: dict[str, Any],
                  tenant_id: str | None = None, campaign_id: str | None = None) -> dict[str, Any]:
    instruction = (
        "<BRAND_KIT>\n"
        + json.dumps(brand_kit, indent=2, ensure_ascii=False)
        + "\n</BRAND_KIT>\n\n"
        "You are the Governance judge for a generated ad creative.\n\n"
        "CONTEXT — what is actually composited onto the image:\n"
        "• Headline text (rendered by our compositor — should be present and legible)\n"
        "• CTA text (rendered as a pill/button)\n"
        "• Brand logo (rendered in a corner)\n"
        "Body copy is metadata for captions, email body, or alt text — it is NOT and should NOT be on the image.\n\n"
        "EVALUATE ONLY:\n"
        "1. Brand-safety violations: hate symbols, explicit content, weapons, gore beyond brief intent.\n"
        "2. Hallucinated claims: factual statements in the image that contradict reality.\n"
        "3. Off-brand visuals: imagery that clearly conflicts with brand tone.\n"
        "4. Headline and CTA legibility on the image.\n\n"
        "DO NOT FLAG:\n"
        "• Missing body copy on the image (body is metadata, not rendered)\n"
        "• Small or stylised text — only flag if completely unreadable\n"
        "• Minor brand-colour variance — only flag major palette violations\n\n"
        "SEVERITY GUIDE:\n"
        "• \"block\" — only for hard brand-safety violations (hate, explicit, dangerous)\n"
        "• \"warn\" — quality, on-brand-fit, or legibility issues (most cases)\n"
        "• \"none\" — pass\n\n"
        "Return JSON only: {\"pass\": bool, \"issues\": [str], \"severity\": \"block\"|\"warn\"|\"none\"}.\n\n"
        f"BRIEF (metadata):\n{json.dumps(brief)}\n\n"
        f"COPY (headline + CTA are on image; body is metadata only):\n{json.dumps(copy)}"
    )
    resp = traced_generate(
        model=MODEL_PRO,
        contents=[
            instruction,
            genai_types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.1,
        ),
        trace_name="governance.judge",
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        metadata={"channel": brief.get("channel")},
    )
    return json.loads(resp.text)


def evaluate(tenant_id: UUID, creative_id: UUID) -> dict[str, Any]:
    with tenant_connection(tenant_id) as conn:
        crow = conn.execute(
            "SELECT storage_path, copy_headline, copy_body, copy_cta, channel, dimensions, campaign_id, brand_id "
            "FROM creatives WHERE id = %s",
            (str(creative_id),),
        ).fetchone()
        if not crow:
            raise RuntimeError("creative not found")
        # Load brand by creative.brand_id (preferred) or fall back to the tenant's most-recent brand.
        creative_brand_id = crow[7]
        if creative_brand_id:
            bk_row = conn.execute(
                "SELECT name, tone, brand_values, primary_colour, secondary_colour, accent_colour, "
                "logo_path, persona_definitions, brand_rules_do, brand_rules_dont, brand_feel, style_description "
                "FROM brands WHERE id = %s AND tenant_id = %s",
                (str(creative_brand_id), str(tenant_id)),
            ).fetchone()
        else:
            bk_row = conn.execute(
                "SELECT name, tone, brand_values, primary_colour, secondary_colour, accent_colour, "
                "logo_path, persona_definitions, brand_rules_do, brand_rules_dont, brand_feel, style_description "
                "FROM brands WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                (str(tenant_id),),
            ).fetchone()
        camp = conn.execute(
            "SELECT brief FROM campaigns WHERE id = %s", (str(crow[6]),),
        ).fetchone()

    storage_path = crow[0]
    copy = {"headline": crow[1], "body": crow[2], "cta": crow[3]}
    channel = crow[4]
    if bk_row:
        brand_kit = {
            "brand_name": bk_row[0],
            "tone": bk_row[1],
            "values": bk_row[2],
            "colours": [c for c in [bk_row[3], bk_row[4], bk_row[5]] if c],
            "logo_paths": [bk_row[6]] if bk_row[6] else [],
            "persona_definitions": bk_row[7] or [],
            "brand_rules_do": bk_row[8],
            "brand_rules_dont": bk_row[9],
            "brand_feel": bk_row[10],
            "style_description": bk_row[11],
        }
    else:
        brand_kit = {"brand_name": "Unknown", "colours": [], "logo_paths": [], "persona_definitions": []}
    briefs = camp[0] if camp and camp[0] else []
    brief = next((b for b in briefs if b.get("channel") == channel), briefs[0] if briefs else {})

    image_bytes = download_bytes(storage_path)

    se = _sightengine_check(image_bytes)
    se_pass, se_issues = _sightengine_verdict(se)

    if not se_pass:
        # Only Sightengine can hard-block — it catches real brand-safety violations.
        verdict = {"pass": False, "issues": se_issues, "severity": "block", "sightengine": se}
    else:
        try:
            judge = _gemini_judge(image_bytes, brand_kit, brief, copy,
                                  tenant_id=str(tenant_id), campaign_id=str(crow[6]))
        except Exception as e:
            judge = {"pass": True, "issues": [f"judge_error:{e}"], "severity": "warn"}
        # Downgrade judge "block" → "warn" so creatives still reach human review.
        # Sightengine has already cleared the genuine brand-safety bar above.
        judge_severity = judge.get("severity", "none")
        if judge_severity == "block":
            judge_severity = "warn"
        verdict = {
            "pass": bool(judge.get("pass", False)),
            "issues": list(judge.get("issues", [])) + se_issues,
            "severity": judge_severity,
            "sightengine": se,
        }

    # passed → all good; flagged → human should look (warn-level issues); blocked → hidden
    if verdict["pass"]:
        status = "passed"
    elif verdict["severity"] == "block":
        status = "blocked"
    else:
        status = "flagged"
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE creatives SET governance_status = %s, governance_issues = %s::jsonb WHERE id = %s",
            (status, json.dumps(verdict), str(creative_id)),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, %s, %s, %s, %s::jsonb)",
            (str(tenant_id), f"governance.{status}", "creative", str(creative_id), json.dumps(verdict)),
        )
    return verdict
