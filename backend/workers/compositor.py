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
    if bar in ("auto", "none"):
        sampled_bg = _avg_rgb(canvas, (text_region_x0, by0, text_region_x1, by1))
        text_hex, shadow = _pick_text_colour(sampled_bg)

    # title_bar overlays draw ACROSS THE FULL CANVAS WIDTH (not just the text region)
    # so they never crop awkwardly at the image/text boundary on wide layouts.
    if bar == "gradient":
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
