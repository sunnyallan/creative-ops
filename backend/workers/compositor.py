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


_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/{name}",
    "/usr/share/fonts/dejavu/{name}",
    "/Library/Fonts/{name}",
    "{name}",  # last resort — Pillow's search
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p.format(name=name), size)
        except OSError:
            continue
    # Loud warning rather than silent bitmap fallback.
    import logging
    logging.getLogger("compositor").warning("font %s not found; using PIL default (no size)", name)
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


def _prep_logo(logo_bytes: bytes, canvas_w: int, target_w_frac: float = 1/8) -> Image.Image | None:
    try:
        logo = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        target_w = int(canvas_w * target_w_frac)
        ratio = target_w / logo.width
        return logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
    except Exception:
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
    brand_hex = _safe_hex(brand_colour, "#1a73e8")
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

    # ---- 3. Headline + subtitle + CTA — content-driven layout ----
    max_text_w = W - 2 * pad

    # Fonts
    head_font_size = max(36, H // 18)
    head_font = _font(head_font_size, bold=True)
    sub_font_size = max(20, H // 34)
    sub_font = _font(sub_font_size, bold=False)
    cta_font_size = max(44, H // 16)  # 2× previous
    cta_font = _font(cta_font_size, bold=True)

    # Wrap copy
    head_lines = _wrap(headline or "", head_font, max_text_w, odraw)[:2]
    if headline and len(_wrap(headline, head_font, max_text_w, odraw)) > 2:
        head_lines[-1] = head_lines[-1].rstrip(".,;:") + "…"

    sub_lines = _wrap(body or "", sub_font, max_text_w, odraw)[:2] if body else []
    if body and len(_wrap(body, sub_font, max_text_w, odraw)) > 2:
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
    cta_px = pad // 2
    cta_py = max(10, cta_font_size // 2)
    if cta_text and cfg.get("cta_style") != "none":
        max_cta_text_w = max_text_w - 2 * cta_px
        cta_wrapped = _wrap(cta_text, cta_font, max_cta_text_w, odraw)
        cta_text = cta_wrapped[0] if cta_wrapped else cta_text[:30]
        ctw_box = odraw.textbbox((0, 0), cta_text, font=cta_font)
        cta_text_w = ctw_box[2] - ctw_box[0]
        cta_text_h = ctw_box[3] - ctw_box[1]
        cta_h = cta_text_h + 2 * cta_py
    text_to_cta_gap = 22 if cta_h else 0

    # Compute required band height & re-position the band
    content_pad = max(20, pad // 2)
    needed_h = head_h + head_to_sub_gap + sub_h + text_to_cta_gap + cta_h + 2 * content_pad
    band_h = max(band_h, needed_h)
    band_h = min(band_h, int(H * 0.5))
    bx0, by0, bx1, by1 = _title_band(cfg.get("title_position", "bottom"), size, band_h)

    # Re-sample background brightness for the new band
    if bar in ("auto", "none"):
        sampled_bg = _avg_rgb(canvas, (bx0, by0, bx1, by1))
        text_hex, shadow = _pick_text_colour(sampled_bg)

    # Redraw band fill if needed (gradient/solid_*). For auto/none, nothing to draw.
    if bar == "gradient":
        # clear old overlay band by recreating overlay layer up to here
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        for i in range(band_h):
            if cfg.get("title_position") == "top":
                alpha = int(220 * ((band_h - i) / band_h))
            else:
                alpha = int(220 * (i / band_h))
            odraw.rectangle([bx0, by0 + i, bx1, by0 + i + 1], fill=(0, 0, 0, alpha))
    elif bar == "solid_dark":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0, 200))
    elif bar == "solid_brand":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([bx0, by0, bx1, by1], fill=brand_rgb + (220,))

    # ---- Layout content in the band ----
    y = by0 + content_pad
    text_x = bx0 + pad

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

    # CTA — pill grows DOWN from y so it never overlaps the subtitle above
    if cta_h:
        y += text_to_cta_gap
        ctw_box = odraw.textbbox((0, 0), cta_text, font=cta_font)
        ctw = ctw_box[2] - ctw_box[0]
        cth = ctw_box[3] - ctw_box[1]
        # Pill top at y; text vertically centred inside the pill
        pill_y0 = y
        pill_y1 = y + cth + 2 * cta_py
        cy0 = pill_y0 + cta_py  # text top inside pill
        cx0 = text_x
        pill_x0 = cx0 - cta_px
        pill_x1 = min(cx0 + ctw + cta_px, bx1 - pad)

        if cfg["cta_style"] == "pill":
            shadow_layer = Image.new("RGBA", size, (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow_layer)
            sdraw.rounded_rectangle(
                [pill_x0 + 3, pill_y0 + 4, pill_x1 + 3, pill_y1 + 4],
                radius=(pill_y1 - pill_y0) // 2, fill=(0, 0, 0, 120),
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(4))
            overlay = Image.alpha_composite(overlay, shadow_layer)
            odraw = ImageDraw.Draw(overlay)
            odraw.rounded_rectangle(
                [pill_x0, pill_y0, pill_x1, pill_y1],
                radius=(pill_y1 - pill_y0) // 2, fill=brand_rgb + (255,),
            )
            odraw.text((cx0, cy0), cta_text, fill="white", font=cta_font)
        elif cfg["cta_style"] == "square":
            odraw.rectangle([pill_x0, pill_y0, pill_x1, pill_y1], fill=brand_rgb + (255,))
            odraw.text((cx0, cy0), cta_text, fill="white", font=cta_font)
        elif cfg["cta_style"] == "underline":
            _draw_text_with_shadow(odraw, (cx0, cy0), cta_text, cta_font, fill=text_hex, shadow=shadow)
            odraw.line([cx0, cy0 + cth + 6, cx0 + ctw, cy0 + cth + 6], fill=brand_hex, width=4)

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
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
