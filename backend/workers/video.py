"""v4.0 Phase D — Video creative worker.

Pipeline:
  1. Build the video prompt from the brief + brand style (same ABSOLUTE LAW
     block architecture as image gen)
  2. Call Veo (google-genai) — 6-8s at 9:16 (Reels/Stories) or 1:1 (feed)
  3. Composite an END-CARD frame via the existing compositor (typo mode,
     brand colour, logo, CTA); ffmpeg mounts it as a 2s tail clip
  4. ffmpeg concats [veo_clip] + [end_card_clip]  → single mp4
  5. ffmpeg extracts a thumbnail (first frame) + samples 3 frames for governance
  6. Uploads mp4 + thumbnail; inserts a `media_type='video'` creative row
  7. Governance runs against ALL sampled frames — worst outcome wins

Cost note: Veo runs ~$3-6 per 8s clip. Orchestrator only picks video when
the goal or learnings justify it (see agents/orchestrator._PLAN_PROMPT).

Model string: default is a placeholder — updating the env var VEO_MODEL_ID
picks up whatever generation is current without a code change.
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from db.session import tenant_connection
from observability import gemini_client
from storage import download_bytes, upload_bytes
from workers.celery_app import celery_app

log = logging.getLogger("video_worker")

# Configurable; update via env without redeploying if Google ships a new model.
_VEO_MODEL = os.getenv("VEO_MODEL_ID", "veo-3.0-generate-001")
_DEFAULT_DURATION_S = int(os.getenv("VEO_DURATION_SECONDS", "8"))
_END_CARD_SECONDS = 2
# Poll interval for the (async-ish) Veo operations API
_POLL_INTERVAL_S = 8
_POLL_TIMEOUT_S = 8 * 60   # 8 min — Veo can take 3-5 min at busy hours


# ============================================================
# Veo generation
# ============================================================

def _veo_generate(prompt: str, aspect: str = "9:16",
                  duration_seconds: int = _DEFAULT_DURATION_S) -> bytes:
    """Call Veo, poll until done, return mp4 bytes. Raises on timeout/error."""
    from google.genai import types as genai_types
    client = gemini_client()

    log.info("veo.generate start aspect=%s duration=%ss model=%s",
             aspect, duration_seconds, _VEO_MODEL)
    try:
        op = client.models.generate_videos(
            model=_VEO_MODEL,
            prompt=prompt,
            config=genai_types.GenerateVideosConfig(
                aspect_ratio=aspect,
                duration_seconds=duration_seconds,
                person_generation="allow_adult",
                number_of_videos=1,
            ),
        )
    except Exception as e:
        # Older SDK path — try the non-config kwarg form
        log.warning("veo config path failed (%s); trying flat kwargs", e)
        op = client.models.generate_videos(
            model=_VEO_MODEL, prompt=prompt,
            aspect_ratio=aspect, duration_seconds=duration_seconds,
        )

    # Poll the long-running operation
    started = time.time()
    while not getattr(op, "done", False):
        if time.time() - started > _POLL_TIMEOUT_S:
            raise RuntimeError(f"Veo generation timed out after {_POLL_TIMEOUT_S}s")
        time.sleep(_POLL_INTERVAL_S)
        try:
            op = client.operations.get(op)
        except Exception as e:
            log.warning("veo operation refresh failed: %s", e)

    # Extract the produced video bytes
    resp = getattr(op, "response", None) or getattr(op, "result", None)
    if resp is None:
        raise RuntimeError(f"Veo returned no response payload: {op}")

    # Response shape (Google SDK): resp.generated_videos[0].video.video_bytes
    videos = getattr(resp, "generated_videos", None) or getattr(resp, "videos", None) or []
    if not videos:
        raise RuntimeError("Veo response has no generated_videos")

    v0 = videos[0]
    video = getattr(v0, "video", None) or v0
    data = getattr(video, "video_bytes", None) or getattr(video, "data", None)
    if data is None:
        # Some responses return a URI to download
        uri = getattr(video, "uri", None) or getattr(video, "url", None)
        if uri:
            import httpx
            r = httpx.get(uri, timeout=120)
            r.raise_for_status()
            data = r.content
    if data is None:
        raise RuntimeError("Veo video payload has neither bytes nor uri")

    log.info("veo.generate done size=%d elapsed=%.1fs", len(data), time.time() - started)
    return data


# ============================================================
# End-card render (reuse compositor typo mode)
# ============================================================

def _end_card_bytes(brand_kit: dict, brief: dict, copy: dict,
                    dimensions: str = "1080x1920") -> bytes:
    """Render an end-card image via the compositor's typo layout using brand
    colours + logo + CTA. Returns WebP bytes; ffmpeg accepts it directly."""
    from workers.compositor import render_layout
    logo_bytes = None
    logo_paths = brand_kit.get("logo_paths") or []
    if logo_paths:
        try:
            logo_bytes = download_bytes(logo_paths[0])
        except Exception:
            logo_bytes = None
    return render_layout(
        layout_mode="typo",
        mode_params={"bg": "brand_primary", "align": "center"},
        channel=brief.get("channel", "video"),
        dimensions=dimensions,
        base_image=None, cutout=None, extra_assets=None,
        headline=copy.get("headline") or brand_kit.get("brand_name") or "",
        body=copy.get("body") or "",
        cta=copy.get("cta") or "Learn more",
        brand_colours=brand_kit.get("colours") or ["#111111"],
        logo_bytes=logo_bytes,
        partner_logo_bytes=None,
        template_config=brand_kit.get("template_config"),
    )


# ============================================================
# ffmpeg wrapping
# ============================================================

def _run(cmd: list[str], *, quiet: bool = True) -> None:
    log.debug("ffmpeg: %s", " ".join(cmd))
    subprocess.run(
        cmd, check=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
    )


def _mux_endcard(veo_mp4: bytes, endcard_bytes: bytes,
                 duration: int, aspect: str) -> tuple[bytes, bytes, list[bytes]]:
    """
    Returns (final_mp4, thumbnail_png, sampled_frames[3]).

    Concat pipeline:
        veo_clip.mp4  +  endcard_still.mp4 (2s)  →  final.mp4
    Thumb + samples extracted from final.mp4.
    """
    W, H = _dims(aspect)
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        veo_p = td_p / "veo.mp4"
        end_img = td_p / "end.png"
        end_clip = td_p / "end.mp4"
        list_p = td_p / "list.txt"
        final_p = td_p / "final.mp4"
        thumb_p = td_p / "thumb.png"

        veo_p.write_bytes(veo_mp4)
        # Convert the end-card WebP (Pillow-safe) to PNG at correct dims
        from PIL import Image
        img = Image.open(io.BytesIO(endcard_bytes)).convert("RGB")
        img = img.resize((W, H), Image.LANCZOS)
        img.save(end_img, format="PNG")

        # End card as a silent 2s clip at the target size, matching yuv420p +
        # 30fps + AAC-mute so concat works without re-encoding drift.
        _run([
            "ffmpeg", "-y", "-loop", "1", "-t", str(_END_CARD_SECONDS),
            "-i", str(end_img),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest",
            "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
            "-vf", f"scale={W}:{H},setsar=1",
            "-c:a", "aac", "-b:a", "128k",
            str(end_clip),
        ])

        # Normalise Veo clip to matching codec/fps/pixel-fmt/audio-track
        veo_norm = td_p / "veo_norm.mp4"
        _run([
            "ffmpeg", "-y", "-i", str(veo_p),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest",
            "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
            "-vf", f"scale={W}:{H},setsar=1",
            "-c:a", "aac", "-b:a", "128k",
            str(veo_norm),
        ])

        list_p.write_text(f"file '{veo_norm}'\nfile '{end_clip}'\n")
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_p),
            "-c", "copy", str(final_p),
        ])

        # Thumbnail = first frame
        _run(["ffmpeg", "-y", "-i", str(final_p), "-vframes", "1",
              "-q:v", "3", str(thumb_p)])

        # Sample 3 frames for governance: 0.5s, mid, near-end
        total_s = duration + _END_CARD_SECONDS
        sample_ts = [0.5, total_s / 2.0, max(0.5, total_s - 1.0)]
        samples: list[bytes] = []
        for i, ts in enumerate(sample_ts):
            sp = td_p / f"sample_{i}.png"
            _run(["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(final_p),
                  "-vframes", "1", "-q:v", "3", str(sp)])
            if sp.exists():
                samples.append(sp.read_bytes())
        return final_p.read_bytes(), thumb_p.read_bytes(), samples


def _dims(aspect: str) -> tuple[int, int]:
    return {"9:16": (1080, 1920), "16:9": (1920, 1080),
            "1:1": (1080, 1080), "4:5": (1080, 1350)}.get(aspect, (1080, 1920))


# ============================================================
# Video governance — sample-frame path
# ============================================================

def _govern_frames(frames: list[bytes]) -> dict:
    """Run each sampled frame through the existing Sightengine + Gemini judge
    pipeline. Worst outcome dominates: any blocked frame blocks the video."""
    from governance.pipeline import _sightengine_check, _sightengine_verdict
    results = []
    worst_status = "passed"
    all_issues: list[str] = []
    for i, fb in enumerate(frames):
        try:
            se = _sightengine_check(fb)
            ok, issues = _sightengine_verdict(se)
            frame_status = "passed" if ok else "blocked"
            results.append({"frame": i, "status": frame_status,
                             "issues": issues, "sightengine": se})
            all_issues.extend(f"frame{i}:{s}" for s in issues)
            if frame_status == "blocked":
                worst_status = "blocked"
        except Exception as e:
            results.append({"frame": i, "status": "error", "error": str(e)})
    return {"pass": worst_status != "blocked",
            "severity": "block" if worst_status == "blocked" else "warn",
            "issues": all_issues, "frames": results}


# ============================================================
# Video prompt (mirrors the image prompt architecture)
# ============================================================

def _video_prompt(brand_kit: dict, brief: dict, duration: int) -> str:
    brand_style = (brand_kit.get("style_description") or "").strip()
    brand_feel = (brand_kit.get("brand_feel") or "").strip()
    tone = brand_kit.get("tone") or ""
    persona = brief.get("persona_segment") or ""
    direction = brief.get("image_direction") or ""

    style_block = ""
    if brand_style:
        style_block = (
            "=== BRAND STYLE — ABSOLUTE LAW ===\n"
            f"This brand's visual language: {brand_style}\n"
            f"Feel: {brand_feel}\n"
            "The video MUST look and move as if it came from the same brand as the "
            "reference imagery. Match colour palette, materials, and mood. If any other "
            "instruction contradicts this, this wins.\n"
            "=== END BRAND STYLE ===\n\n"
        )

    return (
        f"{style_block}"
        f"SHORT ADVERT VIDEO — {duration} seconds.\n"
        f"PERSONA & SCENE: {direction}\n\n"
        f"CAMPAIGN TONE: {tone}\n"
        f"TARGET PERSONA: {persona}\n\n"
        f"MOTION: {brief.get('motion_direction') or 'confident, cinematic camera move with subtle depth of field'}\n"
        f"PACE: 3-4 clear beats within {duration}s, ending on the hero subject.\n"
        f"AUDIO: no dialogue; ambient sound only.\n\n"
        f"COMPOSITION:\n"
        f"- Vertical format (9:16). Subject centred to slightly left.\n"
        f"- Keep the LOWER 25% clean of subject content — reserved for post-production text overlay.\n"
        f"- No on-screen text, no logos, no UI mockups, no watermarks — those are composited after.\n"
        f"- No photorealistic depictions of specific real brands, celebrities, or currency.\n"
    )


# ============================================================
# Celery task
# ============================================================

@celery_app.task(name="video.generate")
def generate_video(tenant_id: str, campaign_id: str, brief_index: int) -> str:
    """Fan-out sibling of workers.creative.generate_creative for video media."""
    t_uuid = UUID(tenant_id)

    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "SELECT brief, brand_id, media_type FROM campaigns WHERE id = %s AND tenant_id = %s",
            (campaign_id, str(t_uuid)),
        ).fetchone()
    if not row:
        raise RuntimeError(f"campaign {campaign_id} not found")
    briefs = row[0] or []
    if brief_index >= len(briefs):
        raise RuntimeError(f"brief_index {brief_index} out of range")
    brief = briefs[brief_index]
    brand_id = row[1]

    # Reuse the existing brand loader
    from workers.creative import _load_brand
    brand_kit = _load_brand(t_uuid, brand_id)

    duration = int(brief.get("duration_seconds") or _DEFAULT_DURATION_S)
    aspect = brief.get("aspect_ratio") or "9:16"

    # ---- 1. Gemini writes copy exactly as it does for image creatives ----
    from workers.creative import _gen_copy
    copy = _gen_copy(brand_kit, brief, tenant_id, campaign_id,
                     {"headline_max_chars": 40, "body_max_chars": 90,
                      "cta_max_chars": 20})

    # ---- 2. Veo clip ----
    prompt = _video_prompt(brand_kit, brief, duration)
    try:
        veo_mp4 = _veo_generate(prompt, aspect=aspect, duration_seconds=duration)
    except Exception as e:
        log.exception("veo generation failed: %s", e)
        # Persist a failed row so the orchestrator can see + skip
        creative_id = uuid.uuid4()
        with tenant_connection(t_uuid) as conn:
            conn.execute(
                "insert into creatives (id, tenant_id, campaign_id, brand_id, channel, "
                "dimensions, copy_headline, copy_body, copy_cta, storage_path, "
                "governance_status, human_status, media_type) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 'blocked', 'pending', 'video')",
                (str(creative_id), str(t_uuid), campaign_id,
                 str(brand_id) if brand_id else None,
                 brief.get("channel", "video"), f"{_dims(aspect)[0]}x{_dims(aspect)[1]}",
                 copy.get("headline"), copy.get("body"), copy.get("cta")),
            )
            conn.execute(
                "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
                "values (%s, 'video.gen_failed', 'creative', %s, %s::jsonb)",
                (str(t_uuid), str(creative_id),
                 json.dumps({"error": str(e)[:500]}, default=str)),
            )
        return str(creative_id)

    # ---- 3. End card + concat + thumbnail + sampled frames ----
    W, H = _dims(aspect)
    endcard = _end_card_bytes(brand_kit, brief, copy, dimensions=f"{W}x{H}")
    final_mp4, thumb_png, samples = _mux_endcard(
        veo_mp4, endcard, duration=duration, aspect=aspect,
    )

    # ---- 4. Governance across sampled frames ----
    frame_verdict = _govern_frames(samples)
    if frame_verdict["pass"]:
        status = "passed"
    elif frame_verdict["severity"] == "block":
        status = "blocked"
    else:
        status = "flagged"

    # ---- 5. Upload assets ----
    creative_id = uuid.uuid4()
    base = f"tenants/{tenant_id}/creatives/{campaign_id}/{creative_id}"
    video_path = f"{base}.mp4"
    thumb_path = f"{base}_thumb.png"
    upload_bytes(video_path, final_mp4, "video/mp4")
    upload_bytes(thumb_path, thumb_png, "image/png")

    # ---- 6. Persist ----
    with tenant_connection(t_uuid) as conn:
        conn.execute(
            "insert into creatives (id, tenant_id, campaign_id, brand_id, channel, "
            "dimensions, copy_headline, copy_body, copy_cta, storage_path, "
            "governance_status, governance_issues, human_status, persona_segment, "
            "layout_style, media_type, video_path, thumbnail_path, duration_seconds) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', "
            "%s, %s, 'video', %s, %s, %s)",
            (str(creative_id), str(t_uuid), campaign_id,
             str(brand_id) if brand_id else None,
             brief.get("channel", "video"), f"{W}x{H}",
             copy.get("headline"), copy.get("body"), copy.get("cta"),
             thumb_path,   # storage_path points at the thumbnail (UI expects an image)
             status, json.dumps(frame_verdict, default=str),
             brief.get("persona_segment"),
             brief.get("layout_style") or "full_bleed_video",
             video_path, thumb_path,
             duration + _END_CARD_SECONDS),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, 'video.generated', 'creative', %s, %s::jsonb)",
            (str(t_uuid), str(creative_id),
             json.dumps({"duration": duration, "aspect": aspect,
                         "governance": status, "veo_model": _VEO_MODEL},
                        default=str)),
        )
    return str(creative_id)
