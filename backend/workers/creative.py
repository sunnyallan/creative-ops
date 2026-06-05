"""Subsystem 3 — Creative Engine.

Celery task: generate copy via Gemini, generate image via Nano Banana
(`gemini-2.5-flash-image`), composite onto channel template, save to Supabase
Storage, insert creatives row, kick off governance.

Image fallback to fal.ai Flux Dev is wired but disabled by default — flip
USE_FALLBACK to True if Nano Banana errors persist.
"""
from __future__ import annotations

import io
import json
import uuid
from typing import Any
from uuid import UUID

from google import genai
from google.genai import types as genai_types

from config import settings
from db.session import tenant_connection
from observability import traced_generate
from storage import download_bytes, upload_bytes
from workers.celery_app import celery_app
from workers.compositor import composite

MODEL_PRO = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-2.5-flash-image"  # Nano Banana

USE_FALLBACK = False
# Set False when Gemini billing is enabled — uses real Nano Banana image gen.
# True = generate a simple placeholder image so the full pipeline runs without billing.
USE_PLACEHOLDER_IMAGE = False


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def _brand_prefix(brand_kit: dict[str, Any]) -> str:
    return (
        "<BRAND_KIT>\n"
        + json.dumps(brand_kit, indent=2, ensure_ascii=False)
        + "\n</BRAND_KIT>\n\n"
        "You are the Creative Engine. Stay strictly on-brand. Reply only with JSON when asked.\n"
    )


def _load_brand_kit(tenant_id: UUID) -> dict[str, Any]:
    with tenant_connection(tenant_id) as conn:
        row = conn.execute(
            "SELECT brand_name, tone, values, colours, fonts, logo_paths, persona_definitions, template_config "
            "FROM brand_kits WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
            (str(tenant_id),),
        ).fetchone()
    if not row:
        raise RuntimeError("brand kit not found")
    return {
        "brand_name": row[0], "tone": row[1], "values": row[2],
        "colours": row[3], "fonts": row[4], "logo_paths": row[5],
        "persona_definitions": row[6], "template_config": row[7],
    }


def _gen_copy(brand_kit: dict[str, Any], brief: dict[str, Any], tenant_id: str, campaign_id: str,
              constraints: dict[str, int] | None = None) -> dict[str, str]:
    c = constraints or {"headline_max_chars": 60, "body_max_chars": 120, "cta_max_chars": 25}
    prompt = (
        _brand_prefix(brand_kit)
        + "TASK: Write ad copy for the brief. Return JSON: "
        '{"headline": str, "body": str, "cta": str}.\n'
        f"HARD LIMITS: headline ≤ {c['headline_max_chars']} chars, "
        f"body ≤ {c['body_max_chars']} chars, cta ≤ {c['cta_max_chars']} chars. "
        "Truncate ideas, never exceed limits.\n\n"
        f"BRIEF:\n{json.dumps(brief, indent=2)}"
    )
    resp = traced_generate(
        model=MODEL_PRO,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.8,
        ),
        trace_name="creative.copy",
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        metadata={"channel": brief.get("channel"), "persona": brief.get("persona_segment")},
    )
    return json.loads(resp.text)


def _gen_placeholder_image(brand_kit: dict[str, Any], brief: dict[str, Any]) -> bytes:
    """Pillow-rendered placeholder so the pipeline runs without billing."""
    import io
    import random
    from PIL import Image, ImageDraw, ImageFont

    colours = brand_kit.get("colours") or ["#1a73e8", "#f4b400"]
    primary = colours[0] if colours[0].startswith("#") else "#1a73e8"
    accent = colours[1] if len(colours) > 1 and colours[1].startswith("#") else "#f4b400"

    # Brief image_direction influences a subtle gradient angle for visual variety
    seed = sum(ord(c) for c in (brief.get("image_direction") or brief.get("channel") or ""))
    random.seed(seed)

    size = (1024, 1024)
    img = Image.new("RGB", size, primary)
    draw = ImageDraw.Draw(img)

    # Diagonal accent stripe
    stripe_w = size[0] // 3
    draw.polygon(
        [(0, size[1]), (stripe_w, size[1]), (size[0], 0), (size[0] - stripe_w, 0)],
        fill=accent,
    )

    # Brand name centered
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
    except OSError:
        font = ImageFont.load_default()
    label = (brand_kit.get("brand_name") or "BRAND").upper()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size[0] - tw) // 2, (size[1] - th) // 2), label, fill="white", font=font)

    # Small "PLACEHOLDER" hint so reviewers know this isn't real Nano Banana output
    try:
        small = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        small = ImageFont.load_default()
    draw.text((20, size[1] - 40), "PLACEHOLDER · enable Gemini billing for real images", fill="white", font=small)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _aspect_ratio_for(dims: str) -> str:
    """Map a 'WxH' string to the closest Nano-Banana-supported aspect ratio."""
    try:
        w, h = dims.lower().split("x")
        r = int(w) / int(h)
    except Exception:
        return "1:1"
    candidates = [
        ("1:1", 1.0), ("4:5", 0.8), ("5:4", 1.25), ("3:4", 0.75), ("4:3", 1.333),
        ("2:3", 0.667), ("3:2", 1.5), ("9:16", 0.5625), ("16:9", 1.778), ("21:9", 2.333),
    ]
    return min(candidates, key=lambda c: abs(c[1] - r))[0]


def _gen_image(brand_kit: dict[str, Any], brief: dict[str, Any]) -> bytes:
    if USE_PLACEHOLDER_IMAGE:
        return _gen_placeholder_image(brand_kit, brief)

    direction = brief.get("image_direction", "")
    tone = brief.get("tone", brand_kit.get("tone", ""))
    persona = brief.get("persona_segment", "")
    dims = brief.get("dimensions", "1080x1080")
    aspect = _aspect_ratio_for(dims)

    brand_name = brand_kit.get("brand_name", "the brand")
    brand_primary = (brand_kit.get("colours") or ["#1a73e8"])[0]

    # Partner colour wins for background if provided; else own brand primary.
    partner_colour = brief.get("_partner_primary_colour")
    bg_colour = partner_colour or brand_primary
    partner_name = brief.get("_partner_name")
    partner_products = brief.get("_partner_products_or_services")

    partner_note = ""
    if partner_name:
        partner_note = (
            f"\nPARTNERSHIP CONTEXT: This is a co-branded offer with '{partner_name}'. "
            f"The background colour {bg_colour} is the partner brand's signature colour. "
            f"The PERSONA ({persona}) only changes the visual STYLE of the hero object "
            f"(materials, finish, mood — luxurious vs everyday, adventure vs leisure) — "
            f"it never changes WHICH object is shown. Object type is locked to {partner_name}'s category.\n"
        )

    if partner_name and partner_products:
        subject_focus = (
            f"a hero object representing ONE of {partner_name}'s actual transactable products: "
            f"{partner_products}. The object MUST be one of these specific products — "
            f"not a generic 'category' object. The persona ({persona}) only changes the styling/context "
            f"(luxury vs everyday, adventure vs leisure), never the object type"
        )
    elif partner_name:
        subject_focus = (
            f"a hero object representing what {partner_name} actually transacts as a product "
            f"(Cleartrip transacts flights/hotels/trains/buses — not gear; "
            f"Zomato transacts food orders — not cooking tools; "
            f"Nykaa transacts beauty products; "
            f"BookMyShow transacts cinema tickets; "
            f"Fitness First transacts gym memberships → kettlebell/dumbbell). "
            f"Never substitute for an object outside what {partner_name} sells"
        )
    else:
        subject_focus = "a hero product or symbolic object that represents the campaign goal"

    prompt = (
        f"HERO BANNER for a partnership campaign.\n\n"
        f"SUBJECT: {subject_focus}.\n"
        f"DO NOT depict any credit card, debit card, payment card, or wallet.\n"
        f"DO NOT depict the brand '{brand_name}' as a product — '{brand_name}' branding will be "
        f"added later as a small logo overlay in post-production; it must not appear inside the image.\n\n"
        f"COMPOSITION — modern DTC advertising (Kapiva, Foxtale, Glossier aesthetic):\n"
        f"• Hero subject takes 45–60% of the frame and SITS IN THE UPPER TWO-THIRDS only\n"
        f"• Subject is FLOATING / placed on a flat solid colour background — NOT a photographic scene\n"
        f"• BACKGROUND COLOUR: solid {bg_colour} fills the entire canvas as the dominant colour\n"
        f"• Subtle depth: gentle radial gradient, soft drop shadow under the subject, "
        f"or abstract shapes/circles in slightly lighter/darker tints of {bg_colour}\n"
        f"• Subject lit cleanly (soft studio light), photographic quality, sharp focus\n"
        f"• CRITICAL — lower 35% of the frame is COMPLETELY EMPTY background colour, "
        f"no subject, no shadow, no decoration. This space is for text overlay.\n"
        f"• Subject MUST NOT extend, cast shadows, or have any element below the upper two-thirds line\n"
        f"{partner_note}\n"
        f"BRAND CONTEXT — {tone}. Audience: {persona}.\n"
        f"CREATIVE DIRECTION — {direction}\n\n"
        f"ABSOLUTE — DO NOT VIOLATE:\n"
        f"• NO credit cards, debit cards, payment cards, wallets, or fintech imagery — only partner-category objects\n"
        f"• NO photographic scene backgrounds (no rooms, gyms, offices, landscapes) — "
        f"background must be the solid colour {bg_colour}\n"
        f"• NO text, letters, words, numbers, watermarks, captions, signs, or labels anywhere in the image\n"
        f"• Product packaging surfaces must be COMPLETELY blank\n"
        f"• No fake brand names, no readable lettering of any kind"
    )
    client = _client()  # hold strong ref so finalizer doesn't close httpx mid-call
    resp = client.models.generate_content(
        model=MODEL_IMAGE,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=genai_types.ImageConfig(aspect_ratio=aspect),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if getattr(part, "inline_data", None) and part.inline_data.data:
            return part.inline_data.data
    if USE_FALLBACK:
        return _gen_image_fallback(prompt)
    raise RuntimeError("no image returned by Nano Banana")


def _gen_image_fallback(prompt: str) -> bytes:
    import fal_client
    result = fal_client.run("fal-ai/flux/dev", arguments={"prompt": prompt})
    import httpx
    url = result["images"][0]["url"]
    return httpx.get(url, timeout=60).content


@celery_app.task(name="creative.generate")
def generate_creative(tenant_id: str, campaign_id: str, brief_index: int) -> str:
    """Generate one creative for campaign[brief_index]."""
    t_uuid = UUID(tenant_id)
    brand_kit = _load_brand_kit(t_uuid)

    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "SELECT brief, copy_constraints, partner_brand FROM campaigns WHERE id = %s AND tenant_id = %s",
            (campaign_id, str(t_uuid)),
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("campaign brief missing")
    briefs: list[dict[str, Any]] = row[0]
    brief = briefs[brief_index]
    copy_constraints = row[1] or {}
    partner_brand: dict | None = row[2]

    # Resolve partner info BEFORE image gen so prompt can use it
    partner_logo_bytes: bytes | None = None
    partner_name: str | None = None
    if partner_brand:
        partner_name = partner_brand.get("name")
        p_path = partner_brand.get("logo_path")
        if p_path:
            try:
                partner_logo_bytes = download_bytes(p_path)
            except Exception:
                partner_logo_bytes = None
        # Stash partner metadata into brief for image gen + compositor
        brief = {
            **brief,
            "_partner_name": partner_name,
            "_partner_primary_colour": partner_brand.get("primary_colour"),
            "_partner_products_or_services": partner_brand.get("products_or_services"),
        }

    copy = _gen_copy(brand_kit, brief, tenant_id, campaign_id, copy_constraints)
    image_bytes = _gen_image(brand_kit, brief)

    brand_colour = (brand_kit.get("colours") or ["#111111"])[0]
    logo_bytes: bytes | None = None
    logo_paths = brand_kit.get("logo_paths") or []
    if logo_paths:
        try:
            logo_bytes = download_bytes(logo_paths[0])
        except Exception:
            logo_bytes = None

    composed = composite(
        channel=brief["channel"],
        dimensions=brief.get("dimensions", "1080x1080"),
        base_image=image_bytes,
        headline=copy.get("headline", ""),
        body=copy.get("body", ""),
        cta=copy.get("cta", ""),
        brand_colour=brand_colour,
        logo_bytes=logo_bytes,
        template_config=brand_kit.get("template_config"),
        partner_logo_bytes=partner_logo_bytes,
        partner_name=partner_name,
    )

    creative_id = uuid.uuid4()
    path = f"tenants/{tenant_id}/creatives/{campaign_id}/{creative_id}.png"
    upload_bytes(path, composed, "image/png")

    with tenant_connection(t_uuid) as conn:
        conn.execute(
            """
            insert into creatives (id, tenant_id, campaign_id, channel, dimensions,
                                   copy_headline, copy_body, copy_cta, storage_path,
                                   governance_status, human_status, persona_segment)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 'pending', %s)
            """,
            (
                str(creative_id), str(t_uuid), campaign_id, brief["channel"], brief["dimensions"],
                copy.get("headline"), copy.get("body"), copy.get("cta"), path,
                brief.get("persona_segment"),
            ),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, %s, %s, %s, %s::jsonb)",
            (str(t_uuid), "creative.generated", "creative", str(creative_id), json.dumps(brief)),
        )

    # Kick governance
    from workers.governance import run_governance
    run_governance.delay(tenant_id, str(creative_id))

    return str(creative_id)
