"""v3.0 — sync a template from Penpot: export the board as SVG, parse
placeholder zones, render a dummy-content preview."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

_APP = str(Path(__file__).resolve().parent.parent)
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from workers.celery_app import celery_app


def _dummy_image(w: int = 800, h: int = 800) -> bytes:
    """Neutral placeholder used for preview rendering."""
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (203, 203, 203))
    d = ImageDraw.Draw(img)
    d.line([0, 0, w, h], fill=(160, 160, 160), width=6)
    d.line([w, 0, 0, h], fill=(160, 160, 160), width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@celery_app.task(name="template.sync")
def sync_template(tenant_id: str, template_id: str) -> dict:
    from db.session import tenant_connection
    from penpot_client import PenpotError, export_frame_svg, find_frame, get_file
    from storage import upload_bytes
    from workers.template_renderer import parse_zones, render_template

    t_uuid = UUID(tenant_id)

    def _fail(msg: str) -> dict:
        with tenant_connection(t_uuid) as conn:
            conn.execute(
                "update templates set sync_status = 'failed', sync_error = %s where id = %s",
                (msg[:500], template_id),
            )
        return {"ok": False, "reason": msg}

    with tenant_connection(t_uuid) as conn:
        row = conn.execute(
            "select penpot_file_id, penpot_page_id, zones from templates "
            "where id = %s and tenant_id = %s",
            (template_id, str(t_uuid)),
        ).fetchone()
    if not row:
        return {"ok": False, "reason": "template not found"}
    file_id, page_id, zones_prev = row
    board_name = (zones_prev or {}).get("_board_name") or ""
    if not board_name:
        return _fail("no board name stored on template")

    # 1. Resolve the frame id by board name
    try:
        file_data = get_file(file_id)
        resolved_page, frame_id, _frame = find_frame(file_data, page_id, board_name)
    except PenpotError as e:
        return _fail(f"Penpot lookup: {e}")
    except Exception as e:
        return _fail(f"Penpot lookup crashed: {e}")

    # 2. Export SVG
    try:
        svg_bytes = export_frame_svg(file_id, resolved_page, frame_id)
    except PenpotError as e:
        return _fail(f"Penpot export: {e}")
    except Exception as e:
        return _fail(f"Penpot export crashed: {e}")

    # 3. Parse placeholder zones
    try:
        zones = parse_zones(svg_bytes)
    except Exception as e:
        return _fail(f"SVG parse: {e}")
    zones["_board_name"] = board_name

    warnings = []
    if "headline" not in zones:
        warnings.append("no #headline layer — headline copy will not appear")
    if not any(k.startswith("image") for k in zones):
        warnings.append("no #image layer — template renders without generated imagery")

    # 4. Render a dummy-content preview
    try:
        preview = render_template(
            svg_bytes,
            headline="Your headline here",
            body="Supporting line goes here.",
            cta="Call to action",
            images=[_dummy_image()],
            slide_pip="1/5",
            out_width=540, out_height=540,
        )
    except Exception as e:
        return _fail(f"preview render: {e}")

    preview_path = f"tenants/{tenant_id}/templates/{template_id}/preview.webp"
    try:
        upload_bytes(preview_path, preview, "image/webp")
    except Exception as e:
        return _fail(f"preview upload: {e}")

    # 5. Persist
    with tenant_connection(t_uuid) as conn:
        conn.execute(
            "update templates set svg_source = %s, zones = %s::jsonb, preview_path = %s, "
            "penpot_page_id = %s, penpot_frame_id = %s, "
            "sync_status = 'synced', sync_error = %s, last_synced_at = now() "
            "where id = %s",
            (
                svg_bytes.decode("utf-8", errors="replace"),
                json.dumps(zones),
                preview_path,
                resolved_page, frame_id,
                ("; ".join(warnings) if warnings else None),
                template_id,
            ),
        )
        conn.execute(
            "insert into audit_log (tenant_id, action, entity, entity_id, meta) "
            "values (%s, %s, %s, %s, %s::jsonb)",
            (str(t_uuid), "template.synced", "template", template_id,
             json.dumps({"zones": [k for k in zones if not k.startswith("_")], "warnings": warnings})),
        )

    return {"ok": True, "zones": [k for k in zones if not k.startswith("_")], "warnings": warnings}
