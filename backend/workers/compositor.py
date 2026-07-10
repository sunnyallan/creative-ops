"""Pillow channel compositor — magazine-quality output.

Improvements over v1:
- Centre-crop image to FILL the canvas (no more brand-colour bars)
- Gradient overlay across lower third instead of opaque title bar
- Multi-line headline with auto-wrap at canvas-aware widths
- Larger fonts, drop shadows for readability over imagery
- Logo with optional white plate for contrast
- Larger CTA pill with shadow

Template config:
  logo_position: top_left | top_right | bottom_left | bottom_right | center | none
  title_bar:     solid_dark | solid_brand | gradient | none
  title_position: top | center | bottom
  cta_style:     pill | underline | square | none
"""
from __future__ import annotations

import io
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def _safe_hex(s: str, default: str = "#000000") -> str:
    s = (s or "").strip()
    return s if s.startswith("#") and len(s) in (4, 7) else default


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _luminance(rgb: tuple[int, int, int]) -> float:
    """0..255 perceived brightness (Rec. 601)."""
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _rgb_variance(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Rough colour-variance score of a canvas region.
    High score (>40) means the region has busy content — text laid over it
    without a safe-zone overlay will be hard to read."""
    from PIL import ImageStat
    region = img.crop(box).convert("RGB").resize((48, 48))
    stat = ImageStat.Stat(region)
    return sum(stat.stddev[:3]) / 3.0


def _avg_rgb(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    region = img.crop(box).resize((32, 32))  # downsample for speed
    r_sum = g_sum = b_sum = 0
    pixels = list(region.convert("RGB").getdata())
    for r, g, b in pixels:
        r_sum += r; g_sum += g; b_sum += b
    n = len(pixels) or 1
    return (r_sum // n, g_sum // n, b_sum // n)


def _relative_lum(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance."""
    def _ch(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def _contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    l1 = _relative_lum(rgb1)
    l2 = _relative_lum(rgb2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_text_colour(bg_rgb: tuple[int, int, int]) -> tuple[str, tuple[int, int, int, int]]:
    """Return (text_hex, shadow_rgba) with the highest WCAG contrast against bg_rgb."""
    white = (255, 255, 255)
    black = (17, 17, 17)
    if _contrast_ratio(bg_rgb, black) >= _contrast_ratio(bg_rgb, white):
        # Dark text wins on light bg → light shadow for crispness
        return "#111111", (255, 255, 255, 160)
    return "#ffffff", (0, 0, 0, 180)


def _parse_dims(dim_str: str) -> tuple[int, int]:
    try:
        w, h = dim_str.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1080


from pathlib import Path

# Geist is bundled in the repo at backend/fonts. Falls back to DejaVu (installed
# in the Docker image via apt) and Pillow's search if anything goes wrong.
_BUNDLED_FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

_FONT_CANDIDATES = {
    True: [  # bold
        str(_BUNDLED_FONTS_DIR / "Geist-Bold.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ],
    False: [  # regular
        str(_BUNDLED_FONTS_DIR / "Geist-Regular.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ],
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    import logging
    logging.getLogger("compositor").warning("no truetype font found; using PIL default (no size)")
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.ImageFont, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Greedy word-wrap respecting pixel width."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_text_with_shadow(draw, xy, text, font, fill="white", shadow=(0, 0, 0, 160), offset=2):
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _logo_box(pos: str, canvas: tuple[int, int], logo: tuple[int, int], pad: int) -> tuple[int, int]:
    cw, ch = canvas
    lw, lh = logo
    if pos == "top_left": return (pad, pad)
    if pos == "top_right": return (cw - lw - pad, pad)
    if pos == "bottom_left": return (pad, ch - lh - pad)
    if pos == "bottom_right": return (cw - lw - pad, ch - lh - pad)
    if pos == "center": return ((cw - lw) // 2, (ch - lh) // 2)
    return (-9999, -9999)


def _opposite_logo_pos(pos: str) -> str:
    return {
        "top_left": "top_right",
        "top_right": "top_left",
        "bottom_left": "bottom_right",
        "bottom_right": "bottom_left",
    }.get(pos, "top_left")


def _title_band(position: str, size: tuple[int, int], band_h: int) -> tuple[int, int, int, int]:
    w, h = size
    if position == "top": return (0, 0, w, band_h)
    if position == "center": return (0, (h - band_h) // 2, w, (h + band_h) // 2)
    return (0, h - band_h, w, h)


def _is_svg(b: bytes) -> bool:
    head = b[:512].lstrip().lower()
    return head.startswith(b"<?xml") and b"<svg" in head[:1024] or head.startswith(b"<svg")


def _svg_to_image(svg_bytes: bytes, target_w: int) -> Image.Image:
    """Rasterise an SVG to an RGBA Image at the target pixel width."""
    import cairosvg
    png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=target_w)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _prep_logo(logo_bytes: bytes, canvas_w: int, target_w_frac: float = 1/8) -> Image.Image | None:
    if not logo_bytes:
        return None
    target_w = int(canvas_w * target_w_frac)
    try:
        if _is_svg(logo_bytes):
            return _svg_to_image(logo_bytes, target_w)
        logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        ratio = target_w / logo.width
        return logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
    except Exception as e:
        import logging
        logging.getLogger("compositor").warning("logo prep failed: %s", e)
        return None


def _single_plate(logo: Image.Image) -> Image.Image:
    plate_pad = max(10, logo.width // 12)
    plate = Image.new("RGBA", (logo.width + plate_pad * 2, logo.height + plate_pad * 2), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(plate)
    pdraw.rounded_rectangle(
        [0, 0, plate.width - 1, plate.height - 1],
        radius=plate_pad, fill=(255, 255, 255, 235),
    )
    plate.paste(logo, (plate_pad, plate_pad), logo)
    return plate


def _co_branded_plate(primary: Image.Image, partner: Image.Image) -> Image.Image:
    """Primary logo + × + partner logo on a single white plate."""
    # Normalise heights so they sit on the same baseline
    h = max(primary.height, partner.height)
    def _resize_to_h(img: Image.Image, h: int) -> Image.Image:
        r = h / img.height
        return img.resize((int(img.width * r), h), Image.LANCZOS)
    primary = _resize_to_h(primary, h)
    partner = _resize_to_h(partner, h)

    gap = max(12, h // 3)
    # "×" glyph between logos
    sep_font = _font(int(h * 0.6), bold=True)
    sep_text = "×"
    tmp_img = Image.new("RGBA", (h * 2, h), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp_img)
    sb = tmp_draw.textbbox((0, 0), sep_text, font=sep_font)
    sep_w = sb[2] - sb[0]
    sep_h = sb[3] - sb[1]

    total_w = primary.width + gap + sep_w + gap + partner.width
    plate_pad = max(12, h // 5)
    plate = Image.new("RGBA", (total_w + plate_pad * 2, h + plate_pad * 2), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(plate)
    pdraw.rounded_rectangle(
        [0, 0, plate.width - 1, plate.height - 1],
        radius=plate_pad, fill=(255, 255, 255, 240),
    )
    x = plate_pad
    plate.paste(primary, (x, plate_pad), primary)
    x += primary.width + gap
    pdraw.text((x, plate_pad + (h - sep_h) // 2 - 4), sep_text, fill=(60, 60, 60), font=sep_font)
    x += sep_w + gap
    plate.paste(partner, (x, plate_pad), partner)
    return plate


def composite(
    channel: str,
    dimensions: str,
    base_image: bytes,
    headline: str,
    cta: str,
    brand_colour: str,
    logo_bytes: bytes | None,
    template_config: dict | None = None,
    partner_logo_bytes: bytes | None = None,
    partner_name: str | None = None,
    body: str = "",
) -> bytes:
    cfg = template_config or {
        "logo_position": "top_right",
        "title_bar": "gradient",
        "title_position": "bottom",
        "cta_style": "pill",
    }
    size = _parse_dims(dimensions)
    W, H = size
    # Resolve CTA colour: template override → brand primary → neutral dark
    cfg_cta_colour = (template_config or {}).get("cta_colour")
    brand_hex = _safe_hex(cfg_cta_colour or brand_colour, "#111111")
    brand_rgb = _hex_rgb(brand_hex)

    # ---- 1. Centre-crop the base image to fill the canvas ----
    src = Image.open(io.BytesIO(base_image)).convert("RGB")
    canvas = ImageOps.fit(src, size, method=Image.LANCZOS, centering=(0.5, 0.5))

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    pad = max(28, W // 32)

    # ---- 2. Title band ----
    # Lighter — references rely on imagery, not heavy overlay bars.
    band_h = max(160, H // 5)
    bx0, by0, bx1, by1 = _title_band(cfg.get("title_position", "bottom"), size, band_h)
    bar = cfg.get("title_bar", "auto")

    # Sample the canvas under the band BEFORE drawing anything to decide text colour
    sampled_bg = _avg_rgb(canvas, (bx0, by0, bx1, by1))
    auto_text_hex, auto_shadow = _pick_text_colour(sampled_bg)

    if bar == "gradient":
        for i in range(band_h):
            if cfg.get("title_position") == "top":
                alpha = int(220 * ((band_h - i) / band_h))
            else:
                alpha = int(220 * (i / band_h))
            odraw.rectangle([bx0, by0 + i, bx1, by0 + i + 1], fill=(0, 0, 0, alpha))
        text_hex, shadow = "#ffffff", (0, 0, 0, 160)
    elif bar == "solid_dark":
        odraw.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0, 200))
        text_hex, shadow = "#ffffff", (0, 0, 0, 160)
    elif bar == "solid_brand":
        odraw.rectangle([bx0, by0, bx1, by1], fill=brand_rgb + (220,))
        text_hex, shadow = _pick_text_colour(brand_rgb)
    else:
        # "auto" or "none" — text sits directly on the image
        text_hex, shadow = auto_text_hex, auto_shadow

    # ---- 3. Headline + subtitle + CTA — aspect-aware layout ----
    # Square (≈1:1): image centred, text spans full canvas width at the bottom.
    # Wide (>1.3): image right half, text in left ~55% at the bottom.
    aspect = W / H
    is_wide = aspect > 1.3

    if is_wide:
        text_region_x0 = pad
        text_region_x1 = int(W * 0.55) - pad // 2
    else:
        text_region_x0 = pad
        text_region_x1 = W - pad

    max_text_w = text_region_x1 - text_region_x0

    # Fixed pixel sizes so text reads identically across channels.
    head_font_size = 62
    head_font = _font(head_font_size, bold=True)
    sub_font_size = 30
    sub_font = _font(sub_font_size, bold=False)
    cta_font_size = 46
    cta_font = _font(cta_font_size, bold=True)

    # Wrap copy — allow up to 3 lines for headline / 3 for body so we don't truncate good copy.
    head_all = _wrap(headline or "", head_font, max_text_w, odraw)
    head_lines = head_all[:3]
    if len(head_all) > 3:
        head_lines[-1] = head_lines[-1].rstrip(".,;:") + "…"

    sub_all = _wrap(body or "", sub_font, max_text_w, odraw) if body else []
    sub_lines = sub_all[:3]
    if len(sub_all) > 3:
        sub_lines[-1] = sub_lines[-1].rstrip(".,;:") + "…"

    # Line heights + gaps
    head_line_h = head_font_size + 8
    sub_line_h = sub_font_size + 4
    head_h = head_line_h * len(head_lines)
    sub_h = sub_line_h * len(sub_lines)
    head_to_sub_gap = 12 if sub_lines else 0

    # CTA sizing (clip width to canvas)
    cta_text = (cta or "").strip()
    cta_h = 0
    # Tighter, more proportional padding — these were over-padded before.
    cta_py = max(8, int(cta_font_size * 0.42))   # vertical padding inside pill
    cta_px = max(16, int(cta_font_size * 0.9))    # horizontal padding inside pill
    if cta_text and cfg.get("cta_style") != "none":
        max_cta_text_w = max_text_w - 2 * cta_px
        cta_wrapped = _wrap(cta_text, cta_font, max_cta_text_w, odraw)
        cta_text = cta_wrapped[0] if cta_wrapped else cta_text[:30]
        # Use ascent+descent for visual height (not bbox top which can include leading)
        ascent, descent = cta_font.getmetrics()
        cta_visual_h = ascent + descent
        cta_h = cta_visual_h + 2 * cta_py
    text_to_cta_gap = max(18, cta_font_size // 2)

    # ---- Position the text block: BOTTOM-LEFT aligned ----
    content_pad = max(20, pad // 2)
    text_block_h = head_h + head_to_sub_gap + sub_h + text_to_cta_gap + cta_h

    bottom_margin = max(pad, H // 14)  # space between text block and canvas bottom
    region_top_y = H - bottom_margin - text_block_h
    bx0 = text_region_x0 - pad
    bx1 = text_region_x1 + pad
    by0 = max(pad, region_top_y - content_pad)
    by1 = H - bottom_margin + content_pad

    # Sample background where the text will sit to pick contrast colour.
    # Also compute variance — high variance means busy content that will
    # eat the text without a safe-zone overlay.
    auto_variance = 0.0
    if bar in ("auto", "none"):
        sampled_bg = _avg_rgb(canvas, (text_region_x0, by0, text_region_x1, by1))
        auto_variance = _rgb_variance(canvas, (text_region_x0, by0, text_region_x1, by1))
        text_hex, shadow = _pick_text_colour(sampled_bg)

    # GUARDRAIL — variance-triggered safe zone.
    # If the text region is busy (variance > 40), promote 'auto' to an
    # implicit gradient using the sampled_bg colour so text has a clean
    # canvas without looking like a hard overlay box.
    VARIANCE_THRESHOLD = 40.0
    is_variance_guarded = bar in ("auto", "none") and auto_variance > VARIANCE_THRESHOLD

    # title_bar overlays draw ACROSS THE FULL CANVAS WIDTH (not just the text region)
    # so they never crop awkwardly at the image/text boundary on wide layouts.
    if is_variance_guarded:
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        grad_top = by0
        grad_h = max(1, H - grad_top)
        r, g, b = sampled_bg
        for i in range(grad_h):
            alpha = int(210 * (i / grad_h))  # transparent at top → opaque at bottom
            odraw.rectangle([0, grad_top + i, W, grad_top + i + 1], fill=(r, g, b, alpha))
        # Re-pick text colour against the solid fill (sampled_bg) since the safe
        # zone will now dominate the region.
        text_hex, shadow = _pick_text_colour(sampled_bg)
    elif bar == "gradient":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        # Fade from transparent at top of text region to opaque at canvas bottom.
        grad_top = by0
        grad_h = max(1, H - grad_top)
        for i in range(grad_h):
            alpha = int(180 * (i / grad_h))
            odraw.rectangle([0, grad_top + i, W, grad_top + i + 1], fill=(0, 0, 0, alpha))
    elif bar == "solid_dark":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([0, by0, W, H], fill=(0, 0, 0, 180))
    elif bar == "solid_brand":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([0, by0, W, H], fill=brand_rgb + (200,))

    # ---- Layout content bottom-anchored, left-aligned ----
    y = region_top_y
    text_x = text_region_x0

    # Headline
    for ln in head_lines:
        _draw_text_with_shadow(odraw, (text_x, y), ln, head_font, fill=text_hex, shadow=shadow)
        y += head_line_h
    if head_lines:
        y -= 4  # trim trailing extra

    # Subtitle (body)
    if sub_lines:
        y += head_to_sub_gap
        for ln in sub_lines:
            _draw_text_with_shadow(odraw, (text_x, y), ln, sub_font, fill=text_hex, shadow=shadow)
            y += sub_line_h
        y -= 2

    # CTA — pill grows DOWN from y. Text is properly centred using font metrics.
    if cta_h:
        y += text_to_cta_gap
        bbox = odraw.textbbox((0, 0), cta_text, font=cta_font)
        ctw = bbox[2] - bbox[0]            # visible glyph width
        ascent, descent = cta_font.getmetrics()

        pill_y0 = y
        pill_y1 = y + ascent + descent + 2 * cta_py
        pill_h = pill_y1 - pill_y0

        pill_x0 = text_x
        pill_x1 = min(text_x + ctw + 2 * cta_px, bx1 - pad)

        # Vertically centre the VISIBLE glyph (not the font cell) in the pill.
        # Pillow's draw.text positions by top-left of the glyph cell; bbox[1] is the
        # ascender offset to the visible top, bbox[3] is the descender extent.
        # We want: text_y + (bbox[1] + bbox[3]) / 2  ==  pill_center
        text_y = pill_y0 + (pill_h - bbox[1] - bbox[3]) // 2
        # Horizontally centre using actual glyph bbox.
        text_x_in_pill = pill_x0 + (pill_x1 - pill_x0 - ctw) // 2 - bbox[0]

        radius = pill_h // 2  # full pill curvature

        # ----- Pick pill colours -----
        # If the brand colour would get lost against the canvas behind the pill,
        # flip to reverse (white pill + dark text). Otherwise use brand pill with
        # text colour auto-picked for contrast against brand.
        pill_bg_sample = _avg_rgb(canvas, (pill_x0, pill_y0, pill_x1, pill_y1))
        brand_vs_bg = _contrast_ratio(brand_rgb, pill_bg_sample)

        if brand_vs_bg < 2.5:
            # Reverse mode — brand pill would blend into bg.
            pill_fill = (255, 255, 255, 255)
            text_fill = "#111111"
        else:
            pill_fill = brand_rgb + (255,)
            # Auto-flip text colour if brand colour is too light to read white on.
            text_fill = "white"
            if _contrast_ratio(brand_rgb, (255, 255, 255)) < 3.0:
                text_fill = "#111111"

        if cfg["cta_style"] == "pill":
            # Subtle drop shadow (smaller offset, less opaque than before).
            shadow_layer = Image.new("RGBA", size, (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow_layer)
            sdraw.rounded_rectangle(
                [pill_x0 + 2, pill_y0 + 3, pill_x1 + 2, pill_y1 + 3],
                radius=radius, fill=(0, 0, 0, 70),
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(3))
            overlay = Image.alpha_composite(overlay, shadow_layer)
            odraw = ImageDraw.Draw(overlay)
            odraw.rounded_rectangle(
                [pill_x0, pill_y0, pill_x1, pill_y1],
                radius=radius, fill=pill_fill,
            )
            odraw.text((text_x_in_pill, text_y), cta_text, fill=text_fill, font=cta_font)
        elif cfg["cta_style"] == "square":
            odraw.rounded_rectangle(
                [pill_x0, pill_y0, pill_x1, pill_y1],
                radius=8, fill=pill_fill,
            )
            odraw.text((text_x_in_pill, text_y), cta_text, fill=text_fill, font=cta_font)
        elif cfg["cta_style"] == "underline":
            # No pill — text only, auto-contrast colour, with brand-coloured underline.
            _draw_text_with_shadow(
                odraw, (text_x, text_y), cta_text, cta_font,
                fill=text_hex, shadow=shadow,
            )
            underline_y = text_y + ascent + 4
            # Underline uses brand colour unless it would be lost against bg, then text_hex.
            underline_fill = brand_hex if brand_vs_bg >= 2.5 else text_hex
            odraw.line([text_x, underline_y, text_x + ctw, underline_y], fill=underline_fill, width=3)

    # Merge band overlay onto canvas
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)

    # ---- 5. Logo(s) — primary at cfg position, partner on opposite corner ----
    primary_pos = cfg.get("logo_position", "top_right")
    if primary_pos != "none":
        try:
            primary = _prep_logo(logo_bytes, W) if logo_bytes else None
            partner = _prep_logo(partner_logo_bytes, W) if partner_logo_bytes else None

            if primary:
                plate = _single_plate(primary)
                box = _logo_box(primary_pos, size, plate.size, pad)
                canvas.paste(plate, box, plate)

            if partner:
                p_plate = _single_plate(partner)
                p_pos = _opposite_logo_pos(primary_pos)
                p_box = _logo_box(p_pos, size, p_plate.size, pad)
                canvas.paste(p_plate, p_box, p_plate)
        except Exception:
            pass

    out = io.BytesIO()
    # WebP @ q82 — ~10× smaller than PNG at equivalent perceived quality.
    # method=6 = slowest/best compression (still fast for our canvases).
    canvas.convert("RGB").save(out, format="WEBP", quality=82, method=6)
    return out.getvalue()


# ============================================================================
# v3.0 — Layout renderer dispatch
# The original composite() above remains the "overlay" renderer, untouched.
# render_layout() routes to it or to one of the new mode renderers below.
# All modes reuse the module helpers (_font, _wrap, _pick_text_colour,
# _prep_logo, _single_plate, _contrast_ratio) and finish as WebP q82.
# ============================================================================

import re as _re


def _webp(canvas: Image.Image) -> bytes:
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="WEBP", quality=82, method=6)
    return out.getvalue()


def _resolve_bg(mode_params: dict, brand_colours: list[str]) -> tuple[int, int, int]:
    """Map 'brand_primary'/'brand_secondary' → actual RGB from the brand palette."""
    key = (mode_params or {}).get("bg", "brand_primary")
    primary = _hex_rgb(_safe_hex(brand_colours[0] if brand_colours else "", "#111111"))
    secondary = _hex_rgb(_safe_hex(
        brand_colours[1] if len(brand_colours) > 1 else (brand_colours[0] if brand_colours else ""),
        "#f2efe9",
    ))
    return secondary if key == "brand_secondary" else primary


def _gradient_canvas(size: tuple[int, int], c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    """Vertical two-stop gradient."""
    W, H = size
    canvas = Image.new("RGB", size)
    px = canvas.load()
    for y in range(H):
        t = y / max(1, H - 1)
        row = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return canvas


def _paste_logos(canvas: Image.Image, logo_bytes, partner_logo_bytes, cfg: dict, pad: int) -> Image.Image:
    """Own logo at cfg position, partner on the opposite corner (reuses v1 helpers)."""
    primary_pos = (cfg or {}).get("logo_position", "top_right")
    if primary_pos == "none":
        return canvas
    W = canvas.width
    try:
        primary = _prep_logo(logo_bytes, W) if logo_bytes else None
        partner = _prep_logo(partner_logo_bytes, W) if partner_logo_bytes else None
        if primary:
            plate = _single_plate(primary)
            canvas.paste(plate, _logo_box(primary_pos, canvas.size, plate.size, pad), plate)
        if partner:
            p_plate = _single_plate(partner)
            canvas.paste(p_plate, _logo_box(_opposite_logo_pos(primary_pos), canvas.size, p_plate.size, pad), p_plate)
    except Exception:
        pass
    return canvas


def _draw_text_stack(
    canvas: Image.Image,
    box: tuple[int, int, int, int],       # x0, y0, x1, y1 region for the stack
    headline: str, body: str, cta: str,
    brand_rgb: tuple[int, int, int],
    *,
    head_size: int = 62, body_size: int = 30, cta_size: int = 46,
    align: str = "left",
    text_rgb: tuple[int, int, int] | None = None,
    anchor: str = "bottom",               # bottom | top | center
) -> Image.Image:
    """Shared headline+body+CTA renderer for the v3 modes. Auto-contrast against
    the region it draws on unless text_rgb is forced."""
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(canvas, "RGBA")
    max_w = x1 - x0

    if text_rgb is None:
        sampled = _avg_rgb(canvas, box)
        text_hex, shadow = _pick_text_colour(sampled)
    else:
        text_hex = "#%02x%02x%02x" % text_rgb
        lum_dark = _contrast_ratio(text_rgb, (17, 17, 17)) < _contrast_ratio(text_rgb, (255, 255, 255))
        shadow = (0, 0, 0, 120) if not lum_dark else (255, 255, 255, 120)

    head_font = _font(head_size, bold=True)
    body_font = _font(body_size, bold=False)
    cta_font = _font(cta_size, bold=True)

    head_lines = _wrap(headline or "", head_font, max_w, draw)[:4]
    # Shrink headline if it wraps more than 3 lines
    while len(head_lines) > 3 and head_size > 36:
        head_size = int(head_size * 0.85)
        head_font = _font(head_size, bold=True)
        head_lines = _wrap(headline or "", head_font, max_w, draw)[:4]
    body_lines = _wrap(body or "", body_font, max_w, draw)[:3] if body else []

    head_lh = head_size + 8
    body_lh = body_size + 6
    ascent, descent = cta_font.getmetrics()
    cta_py = max(8, int(cta_size * 0.42))
    cta_px = max(16, int(cta_size * 0.9))
    cta_h = (ascent + descent + 2 * cta_py) if cta else 0
    gap1 = 14 if body_lines else 0
    gap2 = 24 if cta else 0
    total_h = len(head_lines) * head_lh + gap1 + len(body_lines) * body_lh + gap2 + cta_h

    if anchor == "bottom":
        y = y1 - total_h
    elif anchor == "center":
        y = y0 + max(0, ((y1 - y0) - total_h) // 2)
    else:
        y = y0

    def _line_x(w: int) -> int:
        if align == "center":
            return x0 + (max_w - w) // 2
        return x0

    for ln in head_lines:
        bb = draw.textbbox((0, 0), ln, font=head_font)
        _draw_text_with_shadow(draw, (_line_x(bb[2] - bb[0]), y), ln, head_font, fill=text_hex, shadow=shadow)
        y += head_lh
    y += gap1
    for ln in body_lines:
        bb = draw.textbbox((0, 0), ln, font=body_font)
        _draw_text_with_shadow(draw, (_line_x(bb[2] - bb[0]), y), ln, body_font, fill=text_hex, shadow=shadow)
        y += body_lh
    y += gap2

    if cta:
        cta_text = cta.strip()[:40]
        bb = draw.textbbox((0, 0), cta_text, font=cta_font)
        ctw = bb[2] - bb[0]
        pill_x0 = _line_x(ctw + 2 * cta_px)
        pill_y0, pill_y1 = y, y + cta_h
        radius = cta_h // 2
        pill_sample = _avg_rgb(canvas, (pill_x0, pill_y0, min(pill_x0 + ctw + 2 * cta_px, x1), pill_y1))
        if _contrast_ratio(brand_rgb, pill_sample) < 2.5:
            pill_fill, cta_fill = (255, 255, 255, 255), "#111111"
        else:
            pill_fill = brand_rgb + (255,)
            cta_fill = "white" if _contrast_ratio(brand_rgb, (255, 255, 255)) >= 3.0 else "#111111"
        draw.rounded_rectangle([pill_x0, pill_y0, pill_x0 + ctw + 2 * cta_px, pill_y1], radius=radius, fill=pill_fill)
        text_y = pill_y0 + (cta_h - bb[1] - bb[3]) // 2
        draw.text((pill_x0 + cta_px - bb[0], text_y), cta_text, fill=cta_fill, font=cta_font)

    return canvas


def _duotone(image_bytes: bytes, dark: tuple[int, int, int], light: tuple[int, int, int]) -> bytes:
    """Remap a photo's tones between two brand colours."""
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    lut = []
    for ch in range(3):
        lut.extend(int(dark[ch] + (light[ch] - dark[ch]) * (i / 255)) for i in range(256))
    out = Image.merge("RGB", [img.point(lut[c * 256:(c + 1) * 256]) for c in range(3)])
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def render_layout(
    *,
    layout_mode: str,
    mode_params: dict | None,
    channel: str,
    dimensions: str,
    base_image: bytes | None,
    cutout: bytes | None,
    extra_assets: list[bytes] | None,
    headline: str, body: str, cta: str,
    brand_colours: list[str],
    logo_bytes: bytes | None,
    partner_logo_bytes: bytes | None,
    template_config: dict | None,
    partner_name: str | None = None,
) -> bytes:
    """v3.0 dispatcher. 'overlay' routes to the battle-tested composite();
    every other mode renders here."""
    mp = mode_params or {}
    size = _parse_dims(dimensions)
    W, H = size
    pad = max(28, W // 32)
    cfg = template_config or {}
    brand_hex = _safe_hex((cfg or {}).get("cta_colour") or (brand_colours[0] if brand_colours else ""), "#111111")
    brand_rgb = _hex_rgb(brand_hex)
    primary_rgb = _hex_rgb(_safe_hex(brand_colours[0] if brand_colours else "", "#111111"))
    secondary_rgb = _hex_rgb(_safe_hex(
        brand_colours[1] if len(brand_colours) > 1 else "", "#f2efe9"))

    # ---------- overlay (delegate to v2.2 composite) ----------
    if layout_mode == "overlay":
        img = base_image
        if img and mp.get("post_filter") == "duotone":
            img = _duotone(img, primary_rgb, secondary_rgb)
        if img is None:
            # Defensive: overlay without an image degrades to typo mode.
            layout_mode = "typo"
        else:
            return composite(
                channel=channel, dimensions=dimensions, base_image=img,
                headline=headline, cta=cta, body=body,
                brand_colour=brand_colours[0] if brand_colours else "#111111",
                logo_bytes=logo_bytes, template_config=template_config,
                partner_logo_bytes=partner_logo_bytes, partner_name=partner_name,
            )

    # ---------- text-led modes ----------
    if layout_mode == "typo":
        if mp.get("bg") == "gradient":
            canvas = _gradient_canvas(size, primary_rgb, secondary_rgb)
        else:
            canvas = Image.new("RGB", size, _resolve_bg(mp, brand_colours))
        canvas = _draw_text_stack(
            canvas, (pad, pad + H // 8, W - pad, H - pad), headline, body, cta, brand_rgb,
            head_size=max(72, H // 10), align=mp.get("align", "left"), anchor="center",
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    if layout_mode == "quote":
        canvas = Image.new("RGB", size, _resolve_bg(mp, brand_colours))
        draw = ImageDraw.Draw(canvas)
        qfont = _font(max(160, H // 5), bold=True)
        sampled = _avg_rgb(canvas, (0, 0, W, H))
        q_hex, _ = _pick_text_colour(sampled)
        draw.text((pad, pad // 2), "“", font=qfont, fill=q_hex)
        attribution = f"— {body}" if body else ""
        canvas = _draw_text_stack(
            canvas, (pad, H // 4, W - pad, H - pad), headline, attribution, cta, brand_rgb,
            head_size=max(56, H // 14), anchor="center",
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    if layout_mode == "stat":
        canvas = Image.new("RGB", size, _resolve_bg(mp, brand_colours))
        m = _re.search(r"(₹?\$?[\d,.]+%?[KMBkmb+]?)", headline or "")
        stat = m.group(1) if m else (headline or "").split()[0] if headline else ""
        rest = (headline or "").replace(stat, "", 1).strip(" -—:,")
        draw = ImageDraw.Draw(canvas)
        sfont = _font(max(160, H // 5), bold=True)
        bb = draw.textbbox((0, 0), stat, font=sfont)
        sampled = _avg_rgb(canvas, (0, 0, W, H))
        s_hex, s_shadow = _pick_text_colour(sampled)
        _draw_text_with_shadow(draw, (pad, H // 6), stat, sfont, fill=s_hex, shadow=s_shadow)
        canvas = _draw_text_stack(
            canvas, (pad, H // 6 + (bb[3] - bb[1]) + 40, W - pad, H - pad),
            rest, body, cta, brand_rgb, head_size=max(44, H // 20), anchor="top",
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- image + panel splits ----------
    if layout_mode in ("split_h", "split_v") and base_image:
        canvas = Image.new("RGB", size, primary_rgb)
        frac = float(mp.get("image_frac", 0.6))
        img = Image.open(io.BytesIO(base_image)).convert("RGB")
        if layout_mode == "split_h":
            img_h = int(H * frac)
            canvas.paste(ImageOps.fit(img, (W, img_h), Image.LANCZOS), (0, 0))
            canvas = _draw_text_stack(
                canvas, (pad, img_h + pad // 2, W - pad, H - pad), headline, body, cta, brand_rgb,
                anchor="center",
            )
        else:
            img_w = int(W * frac)
            canvas.paste(ImageOps.fit(img, (img_w, H), Image.LANCZOS), (W - img_w, 0))
            canvas = _draw_text_stack(
                canvas, (pad, pad, W - img_w - pad, H - pad), headline, body, cta, brand_rgb,
                anchor="center",
            )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- cutout family (subject_on_colour / polaroid / minimal) ----------
    if layout_mode == "cutout" and cutout:
        canvas = Image.new("RGB", size, _resolve_bg(mp, brand_colours))
        subject = Image.open(io.BytesIO(cutout)).convert("RGBA")
        scale = float(mp.get("subject_scale", 0.55))
        target_w = int(W * scale)
        r = target_w / max(1, subject.width)
        subject = subject.resize((target_w, int(subject.height * r)), Image.LANCZOS)

        if mp.get("polaroid"):
            frame_pad, chin = 24, 90
            card = Image.new("RGBA", (subject.width + 2 * frame_pad, subject.height + frame_pad + chin), (255, 255, 255, 255))
            card.paste(subject, (frame_pad, frame_pad), subject)
            card = card.rotate(float(mp.get("tilt_deg", -4)), expand=True, resample=Image.BICUBIC)
            subject = card

        sx = (W - subject.width) // 2
        sy = max(pad, int(H * 0.42) - subject.height // 2)
        if mp.get("shadow") and not mp.get("polaroid"):
            sh = Image.new("RGBA", size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse(
                [sx + subject.width // 6, sy + subject.height - 14,
                 sx + subject.width * 5 // 6, sy + subject.height + 26],
                fill=(0, 0, 0, 70))
            canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), sh.filter(ImageFilter.GaussianBlur(8))).convert("RGB"), (0, 0))
        canvas.paste(subject, (sx, sy), subject)
        canvas = _draw_text_stack(
            canvas, (pad, int(H * 0.62), W - pad, H - pad), headline, body, cta, brand_rgb,
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- meme (top/bottom bands) ----------
    if layout_mode == "meme" and base_image:
        band = int(H * float(mp.get("band_frac", 0.16)))
        canvas = Image.new("RGB", size, (12, 12, 12))
        img = ImageOps.fit(Image.open(io.BytesIO(base_image)).convert("RGB"), (W, H - 2 * band), Image.LANCZOS)
        canvas.paste(img, (0, band))
        canvas = _draw_text_stack(
            canvas, (pad, 0, W - pad, band), (headline or "").upper(), "", "", brand_rgb,
            head_size=max(40, band - 36), align="center", anchor="center", text_rgb=(255, 255, 255),
        )
        canvas = _draw_text_stack(
            canvas, (pad, H - band, W - pad, H), body or "", "", cta, brand_rgb,
            head_size=max(28, band // 3), align="center", anchor="center", text_rgb=(255, 255, 255),
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- multi-asset arrangements ----------
    assets = [a for a in (extra_assets or []) if a]
    if layout_mode == "grid" and assets:
        rows, cols = int(mp.get("rows", 2)), int(mp.get("cols", 2))
        band = int(H * 0.24)
        gap = pad // 2
        cell_w = (W - gap * (cols + 1)) // cols
        cell_h = (H - band - gap * (rows + 1)) // rows
        canvas = Image.new("RGB", size, secondary_rgb)
        for i in range(min(len(assets), rows * cols)):
            r_i, c_i = divmod(i, cols)
            cell = ImageOps.fit(Image.open(io.BytesIO(assets[i])).convert("RGB"), (cell_w, cell_h), Image.LANCZOS)
            canvas.paste(cell, (gap + c_i * (cell_w + gap), gap + r_i * (cell_h + gap)))
        ImageDraw.Draw(canvas).rectangle([0, H - band, W, H], fill=primary_rgb)
        canvas = _draw_text_stack(
            canvas, (pad, H - band, W - pad, H - pad // 2), headline, body, cta, brand_rgb, anchor="center",
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    if layout_mode == "collage" and assets:
        canvas = Image.new("RGB", size, _resolve_bg(mp, brand_colours))
        spots = [(0.28, 0.30, 0.42, -8), (0.68, 0.26, 0.36, 6), (0.50, 0.52, 0.34, -3)]
        for i, a in enumerate(assets[:3]):
            cx_f, cy_f, sc, rot = spots[i % len(spots)]
            piece = Image.open(io.BytesIO(a)).convert("RGBA")
            tw = int(W * sc)
            piece = piece.resize((tw, int(piece.height * tw / max(1, piece.width))), Image.LANCZOS)
            piece = piece.rotate(rot, expand=True, resample=Image.BICUBIC)
            canvas.paste(piece, (int(W * cx_f) - piece.width // 2, int(H * cy_f) - piece.height // 2), piece)
        canvas = _draw_text_stack(
            canvas, (pad, int(H * 0.70), W - pad, H - pad), headline, body, cta, brand_rgb,
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    if layout_mode == "before_after" and len(assets) >= 2:
        band = int(H * 0.22)
        half_w = W // 2
        canvas = Image.new("RGB", size, primary_rgb)
        for i in range(2):
            img = ImageOps.fit(Image.open(io.BytesIO(assets[i])).convert("RGB"), (half_w, H - band), Image.LANCZOS)
            canvas.paste(img, (i * half_w, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rectangle([half_w - 3, 0, half_w + 3, H - band], fill=(255, 255, 255, 255))
        chip_font = _font(30, bold=True)
        for i, label in enumerate(("Before", "After")):
            bb = draw.textbbox((0, 0), label, font=chip_font)
            cw = bb[2] - bb[0] + 36
            cx = i * half_w + (half_w - cw) // 2
            draw.rounded_rectangle([cx, pad, cx + cw, pad + 52], radius=26, fill=(17, 17, 17, 210))
            draw.text((cx + 18, pad + (52 - bb[1] - bb[3]) // 2), label, font=chip_font, fill="white")
        canvas = _draw_text_stack(
            canvas, (pad, H - band, W - pad, H - pad // 2), headline, body, cta, brand_rgb, anchor="center",
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- editorial ----------
    if layout_mode == "editorial" and base_image:
        canvas = Image.new("RGB", size, (247, 245, 242))
        win_f = float(mp.get("image_window_frac", 0.42))
        win_w, win_h = int(W * win_f), int(H * 0.46)
        img = ImageOps.fit(Image.open(io.BytesIO(base_image)).convert("RGB"), (win_w, win_h), Image.LANCZOS)
        wx, wy = W - win_w - pad, H - win_h - pad
        ImageDraw.Draw(canvas).rectangle([wx - 4, wy - 4, wx + win_w + 4, wy + win_h + 4], fill=(17, 17, 17))
        canvas.paste(img, (wx, wy))
        canvas = _draw_text_stack(
            canvas, (pad, pad + H // 10, W - pad, wy - pad), headline, body, cta, brand_rgb,
            head_size=max(72, H // 11), anchor="top", text_rgb=(17, 17, 17),
        )
        return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))

    # ---------- fallbacks ----------
    if base_image:
        return composite(
            channel=channel, dimensions=dimensions, base_image=base_image,
            headline=headline, cta=cta, body=body,
            brand_colour=brand_colours[0] if brand_colours else "#111111",
            logo_bytes=logo_bytes, template_config=template_config,
            partner_logo_bytes=partner_logo_bytes, partner_name=partner_name,
        )
    canvas = Image.new("RGB", size, primary_rgb)
    canvas = _draw_text_stack(canvas, (pad, pad, W - pad, H - pad), headline, body, cta, brand_rgb, anchor="center")
    return _webp(_paste_logos(canvas, logo_bytes, partner_logo_bytes, cfg, pad))
