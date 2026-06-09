"""Vision-based reference style extraction.

Given a brand reference image, calls a Gemini vision model to produce a
detailed style description that's later used as part of the master prompt
for that brand's creatives.

Result is saved on brand_references.extracted_style_description; the
aggregated description on brands.style_description is also refreshed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

# Ensure /app is on sys.path regardless of how the worker is invoked.
_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from workers.celery_app import celery_app

VISION_MODEL = "gemini-2.5-flash"  # cheap + good enough for descriptive vision

EXTRACTOR_PROMPT = (
    "You are a senior brand designer analysing a reference banner. "
    "Produce a detailed style description that another designer could use to "
    "create new banners in the same visual language.\n\n"
    "Cover, in plain prose (no headings, no bullet points):\n"
    "• Colour palette — primary, secondary, accent tones (mention specific hex if possible)\n"
    "• Typography — heading style (serif/sans, weight, mood), body style\n"
    "• Composition — subject placement, use of negative space, alignment\n"
    "• Lighting / photographic mood — natural / studio / dramatic\n"
    "• Recurring motifs — shapes, props, treatments\n"
    "• Overall aesthetic — single phrase summary (e.g. \"warm minimal DTC, editorial polish\")\n\n"
    "Be specific and actionable. 150–300 words. Output prose only — no preamble, no JSON."
)


@celery_app.task(name="brand.extract_reference_style")
def extract_reference_style(tenant_id: str, brand_id: str, reference_id: str) -> dict:
    from google import genai
    from google.genai import types as genai_types

    from config import settings
    from db.session import tenant_connection
    from storage import download_bytes

    t_uuid = UUID(tenant_id)

    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "SELECT image_path FROM brand_references WHERE id = %s AND brand_id = %s",
            (reference_id, brand_id),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "reference not found"}
        image_path = row[0]

    # Download the reference image
    try:
        img_bytes = download_bytes(image_path)
    except Exception as e:
        _mark_failed(t_uuid, reference_id, f"download failed: {e}")
        return {"ok": False, "reason": str(e)}

    # Determine mime type from extension (best effort)
    mime = "image/png"
    lower = image_path.lower()
    if lower.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif lower.endswith(".webp"):
        mime = "image/webp"

    # Call Gemini vision
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = client.models.generate_content(
            model=VISION_MODEL,
            contents=[
                EXTRACTOR_PROMPT,
                genai_types.Part.from_bytes(data=img_bytes, mime_type=mime),
            ],
            config=genai_types.GenerateContentConfig(temperature=0.4),
        )
        description = (resp.text or "").strip()
        if not description:
            raise ValueError("empty response")
    except Exception as e:
        _mark_failed(t_uuid, reference_id, f"vision call failed: {e}")
        return {"ok": False, "reason": str(e)}

    # Persist + refresh aggregate
    with tenant_connection(t_uuid) as conn:
        conn.execute(
            "UPDATE brand_references "
            "SET extracted_style_description = %s, extraction_status = 'done', extraction_error = NULL "
            "WHERE id = %s",
            (description, reference_id),
        )
        # Re-aggregate brand.style_description from all completed extractions
        rows = conn.execute(
            "SELECT extracted_style_description FROM brand_references "
            "WHERE brand_id = %s AND extraction_status = 'done' "
            "AND extracted_style_description IS NOT NULL "
            "ORDER BY created_at ASC",
            (brand_id,),
        ).fetchall()
        aggregated = "\n\n---\n\n".join(r[0] for r in rows if r[0])
        conn.execute(
            "UPDATE brands SET style_description = %s, updated_at = now() WHERE id = %s",
            (aggregated, brand_id),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id) "
            "values (%s, %s, %s, %s)",
            (str(t_uuid), "brand_reference.extracted", "brand_reference", reference_id),
        )

    return {"ok": True, "char_count": len(description)}


def _mark_failed(tenant_id: UUID, reference_id: str, error: str) -> None:
    from db.session import tenant_connection
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "UPDATE brand_references "
            "SET extraction_status = 'failed', extraction_error = %s WHERE id = %s",
            (error[:500], reference_id),
        )
