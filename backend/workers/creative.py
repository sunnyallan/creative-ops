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
MODEL_IMAGE = "gemini-3-pro-image"  # Nano Banana Pro — ~3-4x cost, much better prompt adherence

USE_FALLBACK = False
# Set False when Gemini billing is enabled — uses real Nano Banana image gen.
# True = generate a simple placeholder image so the full pipeline runs without billing.
USE_PLACEHOLDER_IMAGE = False


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def _brand_prefix(brand_kit: dict[str, Any]) -> str:
    # Strip internal-only keys (prefixed with _) and stringify anything non-JSON-native.
    public = {k: v for k, v in brand_kit.items() if not k.startswith("_")}
    return (
        "<BRAND_KIT>\n"
        + json.dumps(public, indent=2, ensure_ascii=False, default=str)
        + "\n</BRAND_KIT>\n\n"
        "You are the Creative Engine. Stay strictly on-brand. Reply only with JSON when asked.\n"
    )


def _load_brand(tenant_id: UUID, brand_id: UUID | None) -> dict[str, Any]:
    """Load a brand row (and tenant template config). Falls back to the most
    recent brand if brand_id is None (legacy campaigns or partial migration)."""
    with tenant_connection(tenant_id) as conn:
        if brand_id:
            row = conn.execute(
                "SELECT id, name, tone, brand_values, primary_colour, secondary_colour, accent_colour, "
                "heading_font, body_font, logo_path, persona_definitions, brand_rules_do, brand_rules_dont, "
                "brand_feel, style_description "
                "FROM brands WHERE id = %s AND tenant_id = %s",
                (str(brand_id), str(tenant_id)),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, name, tone, brand_values, primary_colour, secondary_colour, accent_colour, "
                "heading_font, body_font, logo_path, persona_definitions, brand_rules_do, brand_rules_dont, "
                "brand_feel, style_description "
                "FROM brands WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
                (str(tenant_id),),
            ).fetchone()
        if not row:
            raise RuntimeError("brand not found — create one at /brands/new")
        # Template config is tenant-wide
        tcfg_row = conn.execute(
            "SELECT template_config FROM tenants WHERE id = %s",
            (str(tenant_id),),
        ).fetchone()
        template_config = (tcfg_row[0] if tcfg_row else None) or {}

    # Synthesise a "colours" array from primary/secondary/accent for compatibility
    colours = [c for c in [row[4], row[5], row[6]] if c]

    return {
        "brand_id": str(row[0]),  # stringify so the whole dict can be json.dumps'd into prompts
        "brand_name": row[1],
        "tone": row[2],
        "values": row[3],
        "primary_colour": row[4],
        "secondary_colour": row[5],
        "accent_colour": row[6],
        "colours": colours,
        "heading_font": row[7],
        "body_font": row[8],
        "logo_path": row[9],
        "logo_paths": [row[9]] if row[9] else [],  # legacy array shape for compositor
        "persona_definitions": row[10] or [],
        "brand_rules_do": row[11],
        "brand_rules_dont": row[12],
        "brand_feel": row[13],
        "style_description": row[14],
        "template_config": template_config,
    }


def _gen_copy(brand_kit: dict[str, Any], brief: dict[str, Any], tenant_id: str, campaign_id: str,
              constraints: dict[str, int] | None = None) -> dict[str, str]:
    c = constraints or {"headline_max_chars": 30, "body_max_chars": 50, "cta_max_chars": 15}
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

    colours = brand_kit.get("colours") or ["#111111", "#f4b400"]
    primary = colours[0] if colours[0].startswith("#") else "#111111"
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
    brand_primary = (brand_kit.get("colours") or ["#111111"])[0]

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

    # ----- Brand-level constraints injected into the prompt -----
    brand_style = (brand_kit.get("style_description") or "").strip()
    rules_do = (brand_kit.get("brand_rules_do") or "").strip()
    rules_dont = (brand_kit.get("brand_rules_dont") or "").strip()
    brand_feel = (brand_kit.get("brand_feel") or "").strip()

    brand_block = ""
    if brand_style or rules_do or rules_dont or brand_feel:
        parts = []
        if brand_feel:
            parts.append(f"BRAND FEEL: {brand_feel}")
        if brand_style:
            parts.append(f"BRAND STYLE (from your reference banners):\n{brand_style}")
        if rules_do:
            parts.append(f"BRAND RULES — WHAT WE CAN DO:\n{rules_do}")
        if rules_dont:
            parts.append(f"BRAND RULES — WHAT TO AVOID:\n{rules_dont}")
        brand_block = "\n\n".join(parts) + "\n\n"

    # ----- Product-image conditioning -----
    product_image_bytes = brief.get("_product_image_bytes")
    product_block = ""
    if product_image_bytes:
        product_block = (
            "USE THE PROVIDED IMAGE AS THE HERO SUBJECT.\n"
            "Preserve its exact shape, colour, materials, proportions, and identity. "
            "Do not redraw or restyle the subject — only generate the background and supporting "
            "scene around it.\n\n"
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

    # Whether we have rich brand style guidance from reference banners.
    has_rich_brand_style = len(brand_style) > 150

    # Heuristic — detect non-photographic style cues in the brand style description.
    # If the brand is illustrative/vector/pastel/iconographic, we explicitly suppress
    # Nano Banana Pro's photographic-stock default.
    style_lower = brand_style.lower()
    illustrative_cues = [
        "illustrat", "vector", "icon", "flat design", "minimal", "pastel",
        "doodle", "sketch", "graphic", "infograph", "geometric", "abstract shape",
        "wireframe", "mockup", "phone screen", "ui screenshot",
    ]
    is_illustrative_brand = has_rich_brand_style and any(c in style_lower for c in illustrative_cues)

    anti_photo_override = ""
    if is_illustrative_brand:
        anti_photo_override = (
            "\nSTYLE OVERRIDE — THIS BRAND IS NOT PHOTOGRAPHIC.\n"
            "Do NOT generate stock photography. Do NOT use real human models, real hands, "
            "real laptops, real office scenes, real food shots, or photographic textures unless the "
            "BRAND STYLE above explicitly calls for them. Match the BRAND STYLE's aesthetic — "
            "if it's illustrative/vector/flat, output illustrative/vector/flat. If it features "
            "iPhone/UI mockups + floating decorative elements, output that. Treat photographic "
            "realism as a forbidden default.\n"
        )

    if has_rich_brand_style:
        bg_instruction = (
            "BACKGROUND & PALETTE — derived from the BRAND STYLE above. Match the colour palette, "
            "lighting, texture, and design language described in that style block. Do NOT default "
            "to generic photographic scenes or stock-image aesthetics. The look and feel must read "
            "as if it came from the same brand as the reference banners.\n"
        )
        empty_region_colour = "the background colour established by the BRAND STYLE"
    else:
        bg_instruction = (
            f"BACKGROUND COLOUR: solid {bg_colour} fills the entire canvas as the dominant colour. "
            f"Subtle depth via gentle radial gradient or soft drop shadow under the subject.\n"
        )
        empty_region_colour = f"solid {bg_colour}"

    prompt = (
        f"HERO BANNER for a partnership campaign.\n\n"
        # Brand style first — highest priority, made un-overridable
        + (f"=== BRAND STYLE — ABSOLUTE LAW, OVERRIDES ALL DEFAULTS ===\n"
           f"This brand has a specific visual language extracted from its actual reference banners. "
           f"The generated image MUST look as if it came from the same brand. Replicate the "
           f"colour palette, composition, lighting, mood, and design language described below "
           f"EXACTLY. If anything that follows contradicts this style, this style WINS.\n\n"
           f"{brand_block}"
           f"{anti_photo_override}"
           f"=== END BRAND STYLE ===\n\n" if has_rich_brand_style else brand_block)
        + f"{product_block}"
        + f"PERSONA & SCENE: {direction}\n"
        + f"Adapt the brand style to this persona's mood, but never abandon the brand style itself.\n\n"
        + f"SUBJECT: {subject_focus}.\n"
        + f"DO NOT depict any credit card, debit card, payment card, or wallet.\n"
        + f"DO NOT depict the brand '{brand_name}' as a product — '{brand_name}' branding will be "
        + f"added later as a small logo overlay in post-production; it must not appear inside the image.\n\n"
        + f"COMPOSITION:\n"
        + f"• Hero subject takes 40–50% of the frame\n"
        + bg_instruction
        + f"• Render in the medium dictated by the BRAND STYLE above "
          f"(photographic, illustrative, vector, flat — whatever the brand actually uses)\n"
        + f"• ASPECT-AWARE PLACEMENT — interpret based on aspect ratio {aspect}:\n"
        + f"  - If 1:1 (square) — subject CENTRED, occupying the upper-centre to centre of the frame. "
          f"Lower 35% of canvas is EMPTY ({empty_region_colour}) — reserved for headline + CTA text overlay.\n"
        + f"  - If wide (16:9, 2:1, etc.) — subject in the RIGHT HALF, vertically centred. "
          f"Left 50% of canvas is EMPTY ({empty_region_colour}) — reserved for text.\n"
        + f"• Leave clean margins at the top-left and top-right corners for logo overlays.\n"
        + f"• The text overlay area (bottom on square / left on wide) MUST be uncluttered: "
          f"no subject parts, no shadows, no decoration intruding into it.\n"
        + f"{partner_note}\n"
        + f"BRAND CONTEXT — {tone}. Audience: {persona}.\n\n"
        + f"ABSOLUTE — DO NOT VIOLATE:\n"
        + f"• NO credit cards, debit cards, payment cards, wallets, or fintech imagery\n"
        + f"• NO text, letters, words, numbers, watermarks, captions, signs, or labels anywhere in the image\n"
        + f"• Product packaging surfaces must be COMPLETELY blank\n"
        + f"• No fake brand names, no readable lettering of any kind"
    )
    # If a product image was provided, pass it as image input alongside the text prompt
    # so Nano Banana Pro uses it as the actual hero subject.
    carousel_anchor_bytes = brief.get("_carousel_anchor_bytes")
    image_inputs: list[bytes] = []
    if product_image_bytes:
        image_inputs.append(product_image_bytes)
    if carousel_anchor_bytes:
        image_inputs.append(carousel_anchor_bytes)
        # Append carousel-coherence instruction to prompt
        prompt = (
            prompt
            + "\n\nCAROUSEL COHERENCE: an additional image is provided showing slide 1 of this set. "
            "Match its colour palette, background style, decorative motifs, and overall composition "
            "EXACTLY. This slide must look like part of the same set — different copy, but consistent "
            "visual world."
        )

    def _mime(b: bytes) -> str:
        head = b[:12]
        if head[:3] == b"\xff\xd8\xff": return "image/jpeg"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP": return "image/webp"
        return "image/png"

    if image_inputs:
        contents = [
            genai_types.Part.from_bytes(data=b, mime_type=_mime(b)) for b in image_inputs
        ] + [prompt]
    else:
        contents = prompt

    client = _client()  # hold strong ref so finalizer doesn't close httpx mid-call
    resp = client.models.generate_content(
        model=MODEL_IMAGE,
        contents=contents,
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

    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "SELECT brief, copy_constraints, partner_brand, brand_id, product_image_path, "
            "content_type, carousel_slide_count "
            "FROM campaigns WHERE id = %s AND tenant_id = %s",
            (campaign_id, str(t_uuid)),
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("campaign brief missing")
    briefs: list[dict[str, Any]] = row[0]
    brief = briefs[brief_index]
    copy_constraints = row[1] or {}
    partner_brand: dict | None = row[2]
    campaign_brand_id = row[3]
    product_image_path = row[4]
    content_type = row[5] or "banner"
    slide_count = row[6] or 1

    brand_kit = _load_brand(t_uuid, campaign_brand_id)

    # ----- Anchored carousel coherence -----
    # For carousels, slides 2..N receive slide 0's PNG as a visual anchor so the
    # whole set shares palette + composition. Slide 0 has no anchor.
    slide_index = int(brief.get("slide_index") or 0)
    is_carousel = content_type == "social_carousel"
    anchor_image_bytes: bytes | None = None
    if is_carousel and slide_index > 0:
        # Look up slide 0's storage path (if it's already been generated)
        with tenant_connection(t_uuid) as conn:
            anchor_row = conn.execute(
                "SELECT storage_path FROM creatives WHERE campaign_id = %s AND slide_index = 0 "
                "AND storage_path IS NOT NULL LIMIT 1",
                (campaign_id,),
            ).fetchone()
        if anchor_row and anchor_row[0]:
            try:
                anchor_image_bytes = download_bytes(anchor_row[0])
            except Exception:
                anchor_image_bytes = None
        # If slide 0 isn't ready yet, requeue self with a delay so we anchor on the real one.
        if anchor_image_bytes is None:
            import logging
            logging.getLogger("creative").info(
                "carousel slide %s waiting on slide 0; requeueing in 10s", slide_index
            )
            generate_creative.apply_async(
                args=[tenant_id, campaign_id, brief_index], countdown=10,
            )
            return f"deferred:slide_{slide_index}"

    # Load product image if present
    product_image_bytes: bytes | None = None
    if product_image_path:
        try:
            product_image_bytes = download_bytes(product_image_path)
        except Exception as e:
            import logging
            logging.getLogger("creative").warning("product image load failed: %s", e)
    # Stash for use deeper in pipeline
    brief["_product_image_bytes"] = product_image_bytes
    brief["_carousel_anchor_bytes"] = anchor_image_bytes
    brief["_content_type"] = content_type
    brief["_slide_index"] = slide_index
    brief["_total_slides"] = slide_count

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
    path = f"tenants/{tenant_id}/creatives/{campaign_id}/{creative_id}.webp"
    upload_bytes(path, composed, "image/webp")

    with tenant_connection(t_uuid) as conn:
        conn.execute(
            """
            insert into creatives (id, tenant_id, campaign_id, brand_id, channel, dimensions,
                                   copy_headline, copy_body, copy_cta, storage_path,
                                   governance_status, human_status, persona_segment, slide_index)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 'pending', %s, %s)
            """,
            (
                str(creative_id), str(t_uuid), campaign_id,
                str(campaign_brand_id) if campaign_brand_id else None,
                brief["channel"], brief["dimensions"],
                copy.get("headline"), copy.get("body"), copy.get("cta"), path,
                brief.get("persona_segment"),
                slide_index,
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
