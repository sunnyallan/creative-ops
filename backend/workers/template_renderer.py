"""v3.0 — fill a Penpot-exported SVG template and rasterize it.

Placeholder convention (layer names in Penpot):
  #headline #body #cta            → text nodes, content replaced (shrink-to-fit)
  #image #image2 … #imageN        → geometry replaced by the generated asset
  #logo #partner_logo             → brand / partner logo bytes
  #slide_pip                      → "n/N" carousel indicator text

Everything else in the SVG renders exactly as designed — static brand
decoration stays untouched. Rasterization via cairosvg (dep since v1.13);
fonts resolve through fontconfig, so Geist + DejaVu (baked into the image)
are the safe families for designers to use.
"""
from __future__ import annotations

import base64
import re
from typing import Any

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
NSMAP = {"svg": SVG_NS, "xlink": XLINK_NS}

TEXT_KEYS = ("headline", "body", "cta", "slide_pip")
IMAGE_KEY_RE = re.compile(r"^image(\d*)$")
LOGO_KEYS = ("logo", "partner_logo")


def _placeholder_key(el: etree._Element) -> str | None:
    """Match an element against the placeholder set via common name attrs.
    Penpot exports layer names into id / data-name / aria-label depending on
    element type and version; '#' may be stripped or sanitised."""
    for attr in ("id", "data-name", "aria-label", "name", "data-testid"):
        raw = el.get(attr)
        if not raw:
            continue
        key = raw.strip().lstrip("#").strip().lower().replace("-", "_").replace(" ", "_")
        if key in TEXT_KEYS or key in LOGO_KEYS or IMAGE_KEY_RE.match(key):
            return key
    return None


def parse_zones(svg_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Scan the SVG for placeholder nodes; return {key: {kind, x, y, w, h}}."""
    root = etree.fromstring(svg_bytes)
    zones: dict[str, dict[str, Any]] = {}
    for el in root.iter():
        key = _placeholder_key(el)
        if not key or key in zones:
            continue
        kind = "text" if (key in TEXT_KEYS) else ("logo" if key in LOGO_KEYS else "image")
        box = _bbox_of(el)
        zones[key] = {"kind": kind, **box}
    return zones


def _bbox_of(el: etree._Element) -> dict[str, float]:
    """Best-effort geometry: direct x/y/width/height, else scan child rects."""
    def _f(v):
        try:
            return float(re.sub(r"[a-z%]+$", "", v))
        except (TypeError, ValueError):
            return None

    x, y = _f(el.get("x")), _f(el.get("y"))
    w, h = _f(el.get("width")), _f(el.get("height"))
    if w and h:
        return {"x": x or 0.0, "y": y or 0.0, "w": w, "h": h}
    rect = el.find(f".//{{{SVG_NS}}}rect")
    if rect is not None:
        return {
            "x": _f(rect.get("x")) or 0.0, "y": _f(rect.get("y")) or 0.0,
            "w": _f(rect.get("width")) or 0.0, "h": _f(rect.get("height")) or 0.0,
        }
    return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}


def _set_text(el: etree._Element, value: str) -> None:
    """Replace the visible text of a placeholder node, shrink-to-fit by width.
    Handles Penpot's <text><tspan>… nesting: first tspan gets the value,
    remaining tspans are emptied."""
    tspans = el.findall(f".//{{{SVG_NS}}}tspan")
    targets = tspans if tspans else ([el] if el.tag == f"{{{SVG_NS}}}text" else el.findall(f".//{{{SVG_NS}}}text"))
    if not targets:
        return
    first = targets[0]
    first.text = value
    for extra in targets[1:]:
        extra.text = ""

    # Shrink-to-fit: rough width estimate at 0.55em per char.
    box = _bbox_of(el)
    style_holder = first if first.get("font-size") or (first.get("style") and "font-size" in first.get("style", "")) else el
    fs = _extract_font_size(style_holder) or _extract_font_size(el) or 32.0
    if box["w"] > 0 and value:
        est_w = len(value) * fs * 0.55
        if est_w > box["w"]:
            new_fs = max(12.0, fs * (box["w"] / est_w))
            _apply_font_size(first, new_fs)


def _extract_font_size(el: etree._Element) -> float | None:
    v = el.get("font-size")
    if v:
        try:
            return float(re.sub(r"[a-z]+$", "", v))
        except ValueError:
            pass
    style = el.get("style") or ""
    m = re.search(r"font-size:\s*([\d.]+)", style)
    return float(m.group(1)) if m else None


def _apply_font_size(el: etree._Element, size: float) -> None:
    if el.get("font-size"):
        el.set("font-size", f"{size:.1f}")
        return
    style = el.get("style") or ""
    if "font-size" in style:
        el.set("style", re.sub(r"font-size:\s*[\d.]+[a-z]*", f"font-size:{size:.1f}px", style))
    else:
        el.set("style", (style + f";font-size:{size:.1f}px").lstrip(";"))


def _swap_image(root: etree._Element, el: etree._Element, image_bytes: bytes, mime: str) -> None:
    """Replace a placeholder's geometry with an <image> carrying the asset."""
    box = _bbox_of(el)
    if box["w"] <= 0 or box["h"] <= 0:
        return
    b64 = base64.b64encode(image_bytes).decode()
    img = etree.SubElement(root, f"{{{SVG_NS}}}image")
    img.set("x", str(box["x"]))
    img.set("y", str(box["y"]))
    img.set("width", str(box["w"]))
    img.set("height", str(box["h"]))
    img.set(f"{{{XLINK_NS}}}href", f"data:{mime};base64,{b64}")
    img.set("preserveAspectRatio", "xMidYMid slice")
    # Insert directly after the placeholder so it stacks above the placeholder
    # rectangle but below any later decoration layers.
    parent = el.getparent()
    if parent is not None:
        parent.insert(parent.index(el) + 1, img)
        root.remove(img)


def _detect_mime(b: bytes) -> str:
    head = b[:12]
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in b[:2000]:
        return "image/svg+xml"
    return "image/png"


def render_template(
    svg_source: str | bytes,
    *,
    headline: str = "",
    body: str = "",
    cta: str = "",
    images: list[bytes] | None = None,      # fills #image, #image2, … in order
    logo_bytes: bytes | None = None,
    partner_logo_bytes: bytes | None = None,
    slide_pip: str | None = None,           # e.g. "2/5"
    out_width: int = 1080,
    out_height: int = 1080,
) -> bytes:
    """Fill placeholders and rasterize to WebP at the requested dimensions."""
    import io

    import cairosvg
    from PIL import Image

    svg_bytes = svg_source.encode() if isinstance(svg_source, str) else svg_source
    root = etree.fromstring(svg_bytes)

    images = list(images or [])
    text_values = {"headline": headline, "body": body, "cta": cta, "slide_pip": slide_pip or ""}

    for el in list(root.iter()):
        key = _placeholder_key(el)
        if not key:
            continue
        if key in TEXT_KEYS:
            _set_text(el, text_values.get(key, ""))
        elif key in LOGO_KEYS:
            payload = logo_bytes if key == "logo" else partner_logo_bytes
            if payload:
                _swap_image(root, el, payload, _detect_mime(payload))
        else:
            m = IMAGE_KEY_RE.match(key)
            if m:
                idx = int(m.group(1) or "1") - 1
                if 0 <= idx < len(images):
                    _swap_image(root, el, images[idx], _detect_mime(images[idx]))

    filled = etree.tostring(root)
    png = cairosvg.svg2png(bytestring=filled, output_width=out_width, output_height=out_height)

    out = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(out, format="WEBP", quality=82, method=6)
    return out.getvalue()
