"""v3.0 Layout registry — 20 predefined creative layout styles.

Each layout declares:
  asset_plan          what image assets the layout needs:
                        "none"           → no image generation at all (typography-led)
                        "full"           → one full-canvas image (v2.2 behaviour)
                        "subject_cutout" → one subject on white → rembg → transparent RGBA
                        "multi:N"        → N smaller assets (collage / grid / before-after)
  image_prompt_fragment  merged into the Nano Banana Pro prompt UNDER the brand
                         style block (brand style stays absolute law; the fragment
                         shapes medium + composition only)
  compositor_mode     which renderer in compositor.py draws the final canvas
  mode_params         renderer tuning (frame flags, whitespace ratios, grid shape…)

The registry is intentionally code-resident (same pattern as BUILTIN_CHANNELS):
adding a layout is a code change, picking one is user/AI data.
"""
from __future__ import annotations

from typing import Any, TypedDict


class Layout(TypedDict, total=False):
    key: str
    name: str
    description: str
    asset_plan: str
    image_prompt_fragment: str
    compositor_mode: str
    mode_params: dict[str, Any]


LAYOUTS: dict[str, Layout] = {
    "full_bleed_photo": {
        "key": "full_bleed_photo",
        "name": "Full-bleed photo",
        "description": "Image fills the whole canvas; text overlaid in the clean zone. The classic ad look.",
        "asset_plan": "full",
        "image_prompt_fragment": "",  # v2.2 default prompt applies unchanged
        "compositor_mode": "overlay",
        "mode_params": {},
    },
    "typo_hero": {
        "key": "typo_hero",
        "name": "Typography hero",
        "description": "No imagery — a huge, confident headline on the brand colour. Fast, cheap, bold.",
        "asset_plan": "none",
        "image_prompt_fragment": "",
        "compositor_mode": "typo",
        "mode_params": {"bg": "brand_primary", "align": "left"},
    },
    "subject_on_colour": {
        "key": "subject_on_colour",
        "name": "Subject on colour",
        "description": "A cutout subject floats on a flat brand-colour field. Clean DTC product look.",
        "asset_plan": "subject_cutout",
        "image_prompt_fragment": "Single hero subject, studio-lit, centred, no props, no scene.",
        "compositor_mode": "cutout",
        "mode_params": {"bg": "brand_primary", "subject_scale": 0.55, "shadow": True},
    },
    "split_horizontal": {
        "key": "split_horizontal",
        "name": "Horizontal split",
        "description": "Image in the top two-thirds, a solid text band along the bottom.",
        "asset_plan": "full",
        "image_prompt_fragment": "Composition fills the frame edge-to-edge; subject centred.",
        "compositor_mode": "split_h",
        "mode_params": {"image_frac": 0.62},
    },
    "split_vertical": {
        "key": "split_vertical",
        "name": "Vertical split",
        "description": "Image on the right half, a solid colour panel with text on the left.",
        "asset_plan": "full",
        "image_prompt_fragment": "Composition fills the frame edge-to-edge; subject centred.",
        "compositor_mode": "split_v",
        "mode_params": {"image_frac": 0.55},
    },
    "illustrated_flat": {
        "key": "illustrated_flat",
        "name": "Flat illustration",
        "description": "Flat vector-style illustration with simple shapes and brand palette.",
        "asset_plan": "full",
        "image_prompt_fragment": (
            "MEDIUM: flat vector illustration — 2D shapes, no gradients beyond subtle duotones, "
            "clean geometric forms, generous negative space. Absolutely no photography."
        ),
        "compositor_mode": "overlay",
        "mode_params": {},
    },
    "render_3d": {
        "key": "render_3d",
        "name": "3D render",
        "description": "Soft 3D clay / glossy render of the subject. Playful, modern product feel.",
        "asset_plan": "full",
        "image_prompt_fragment": (
            "MEDIUM: soft 3D render — clay-like or glossy plastic materials, rounded forms, "
            "studio lighting with soft shadows, subtle depth of field. No photography."
        ),
        "compositor_mode": "overlay",
        "mode_params": {},
    },
    "gradient_typo": {
        "key": "gradient_typo",
        "name": "Gradient typography",
        "description": "Big type over a smooth brand-colour gradient. Zero imagery, all mood.",
        "asset_plan": "none",
        "image_prompt_fragment": "",
        "compositor_mode": "typo",
        "mode_params": {"bg": "gradient", "align": "center"},
    },
    "editorial_magazine": {
        "key": "editorial_magazine",
        "name": "Editorial magazine",
        "description": "Magazine-style: oversized headline, small framed image window, lots of air.",
        "asset_plan": "full",
        "image_prompt_fragment": "Editorial photography, restrained, gallery-like framing.",
        "compositor_mode": "editorial",
        "mode_params": {"image_window_frac": 0.42},
    },
    "polaroid_frame": {
        "key": "polaroid_frame",
        "name": "Polaroid frame",
        "description": "The image sits in a tilted polaroid card on a colour background.",
        "asset_plan": "subject_cutout",
        "image_prompt_fragment": "Single subject, warm candid feel, centred.",
        "compositor_mode": "cutout",
        "mode_params": {"bg": "brand_secondary", "polaroid": True, "tilt_deg": -4, "subject_scale": 0.5},
    },
    "collage": {
        "key": "collage",
        "name": "Collage",
        "description": "Three cutout elements scattered with playful rotation on a colour field.",
        "asset_plan": "multi:3",
        "image_prompt_fragment": "Single isolated subject, studio-lit, no scene.",
        "compositor_mode": "collage",
        "mode_params": {"bg": "brand_primary", "count": 3},
    },
    "duotone": {
        "key": "duotone",
        "name": "Duotone",
        "description": "Photograph remapped to two brand colours. Striking and unmistakably on-palette.",
        "asset_plan": "full",
        "image_prompt_fragment": "High-contrast photography with strong shapes and clear silhouette.",
        "compositor_mode": "overlay",
        "mode_params": {"post_filter": "duotone"},
    },
    "neon_dark": {
        "key": "neon_dark",
        "name": "Neon dark",
        "description": "Neon-lit subject on near-black. Nightlife / gaming / launch energy.",
        "asset_plan": "full",
        "image_prompt_fragment": (
            "Dark scene, near-black background, subject rimmed with neon accent light in the "
            "brand accent colour, cinematic glow, high contrast."
        ),
        "compositor_mode": "overlay",
        "mode_params": {},
    },
    "minimal_whitespace": {
        "key": "minimal_whitespace",
        "name": "Minimal whitespace",
        "description": "A small subject and a lot of calm, empty space. Premium restraint.",
        "asset_plan": "subject_cutout",
        "image_prompt_fragment": "Single small refined subject, immaculate studio light.",
        "compositor_mode": "cutout",
        "mode_params": {"bg": "brand_secondary", "subject_scale": 0.3, "shadow": True},
    },
    "product_grid": {
        "key": "product_grid",
        "name": "Product grid",
        "description": "A tidy 2×2 grid of product shots. Catalogue energy, retail-ready.",
        "asset_plan": "multi:4",
        "image_prompt_fragment": "Single isolated product, studio-lit, consistent angle.",
        "compositor_mode": "grid",
        "mode_params": {"rows": 2, "cols": 2},
    },
    "quote_card": {
        "key": "quote_card",
        "name": "Quote card",
        "description": "Large quotation marks and a testimonial-style pull-quote. No imagery.",
        "asset_plan": "none",
        "image_prompt_fragment": "",
        "compositor_mode": "quote",
        "mode_params": {"bg": "brand_secondary"},
    },
    "stat_callout": {
        "key": "stat_callout",
        "name": "Stat callout",
        "description": "One giant number with a supporting line. Perfect for research-driven posts.",
        "asset_plan": "none",
        "image_prompt_fragment": "",
        "compositor_mode": "stat",
        "mode_params": {"bg": "brand_primary"},
    },
    "meme_bold": {
        "key": "meme_bold",
        "name": "Bold caption",
        "description": "Bold top and bottom text bands with the image in the middle. Meme-adjacent, social-native.",
        "asset_plan": "full",
        "image_prompt_fragment": "Expressive single moment, clear central subject, room above and below.",
        "compositor_mode": "meme",
        "mode_params": {"band_frac": 0.16},
    },
    "pattern_bg": {
        "key": "pattern_bg",
        "name": "Pattern background",
        "description": "A seamless icon pattern in brand tints behind the message.",
        "asset_plan": "full",
        "image_prompt_fragment": (
            "Seamless repeating pattern of small flat icons related to the topic, brand-colour tints "
            "on brand-colour background, uniform density, no focal subject, decorative wallpaper style."
        ),
        "compositor_mode": "overlay",
        "mode_params": {"force_safe_zone": True},
    },
    "before_after": {
        "key": "before_after",
        "name": "Before / after",
        "description": "Split comparison — two states side by side with a divider.",
        "asset_plan": "multi:2",
        "image_prompt_fragment": "Single clear scene state, consistent camera angle and framing.",
        "compositor_mode": "before_after",
        "mode_params": {},
    },
}


def get_layout(key: str) -> Layout:
    return LAYOUTS.get(key, LAYOUTS["full_bleed_photo"])


def asset_plan_of(key: str) -> tuple[str, int]:
    """Returns (plan, count). e.g. ('multi', 3) or ('full', 1) or ('none', 0)."""
    plan = get_layout(key).get("asset_plan", "full")
    if plan == "none":
        return "none", 0
    if plan.startswith("multi:"):
        return "multi", int(plan.split(":", 1)[1])
    return plan, 1


def registry_for_prompt() -> str:
    """Compact one-line-per-layout listing used by the auto-pick prompt."""
    return "\n".join(
        f"- {l['key']}: {l['description']}" for l in LAYOUTS.values()
    )


def registry_for_api() -> list[dict]:
    """Public listing for the frontend layout picker."""
    return [
        {"key": l["key"], "name": l["name"], "description": l["description"],
         "asset_plan": l["asset_plan"]}
        for l in LAYOUTS.values()
    ]
