"""v4.0 Phase C — Social watcher.

Runs hourly via Celery beat. For every connected Meta account:
  1. Fetch the last N IG media + FB page posts (whether we authored them or not)
  2. Upsert them into social_posts (unique on tenant + platform + post_ref)
  3. Poll the latest insights for anything posted within the last 30 days
  4. Append to metrics_history so the learning loop can distill trends
     (best time, best format, best tag, etc.)

Watching non-authored posts is deliberate: brands post from many tools, and
learning "what worked last Tuesday" is more valuable than only measuring
what our orchestrator published. The distiller in Phase A can pick up
patterns across the whole channel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db.session import get_pool, tenant_connection
from token_crypto import decrypt
from workers.celery_app import celery_app

log = logging.getLogger("social_watcher")

_MAX_MEDIA_PER_ACCOUNT = 25
_METRIC_RECENCY_DAYS = 30


@celery_app.task(name="social.watch")
def watch_all_connections() -> dict:
    """Sweep every connected Meta account and refresh social_posts + metrics."""
    from meta_client import (get_ig_insights, list_ig_media, list_page_posts,
                             get_page_post_insights)

    pool = get_pool()
    with pool.connection() as conn:
        # Service-role bypasses RLS; we pull ids + tokens ourselves.
        conns = conn.execute(
            "SELECT id, tenant_id, selected_page_id, selected_page_access_token, "
            "selected_ig_user_id FROM meta_connections WHERE status = 'connected'"
        ).fetchall()

    processed = 0
    errors: list[str] = []

    for row in conns:
        connection_id, tenant_id, page_id, enc_page_token, ig_user_id = row
        try:
            page_token = decrypt(enc_page_token) if enc_page_token else None
            if not page_token:
                errors.append(f"conn {connection_id}: no page token")
                continue

            # ---- Instagram media
            if ig_user_id:
                try:
                    media = list_ig_media(ig_user_id, page_token, limit=_MAX_MEDIA_PER_ACCOUNT)
                except Exception as e:
                    errors.append(f"conn {connection_id} ig list: {e}")
                    media = []
                for m in media:
                    _upsert_and_poll_ig(
                        tenant_id=tenant_id, connection_id=connection_id,
                        media=m, page_token=page_token,
                    )
                    processed += 1

            # ---- Facebook page posts
            if page_id:
                try:
                    posts = list_page_posts(page_id, page_token, limit=_MAX_MEDIA_PER_ACCOUNT)
                except Exception as e:
                    errors.append(f"conn {connection_id} fb list: {e}")
                    posts = []
                for p in posts:
                    _upsert_and_poll_fb(
                        tenant_id=tenant_id, connection_id=connection_id,
                        post=p, page_token=page_token,
                    )
                    processed += 1
        except Exception as e:
            log.exception("social_watcher: connection %s failed", connection_id)
            errors.append(f"conn {connection_id}: {e}")

    return {"processed": processed, "errors": errors[:20]}


# ============================================================
# Helpers
# ============================================================

def _upsert_and_poll_ig(
    *, tenant_id, connection_id, media: dict[str, Any], page_token: str,
):
    from meta_client import get_ig_insights

    from datetime import datetime as _dt
    media_id = media.get("id")
    caption = media.get("caption") or ""
    permalink = media.get("permalink")
    media_type = (media.get("media_type") or "").lower()
    post_type_map = {"image": "feed", "carousel_album": "carousel", "video": "reel"}
    post_type = post_type_map.get(media_type, "feed")
    posted_at_raw = media.get("timestamp")
    posted_at = None
    if posted_at_raw:
        try:
            posted_at = _dt.fromisoformat(posted_at_raw.replace("Z", "+00:00"))
        except Exception:
            pass
    # Only poll insights if posted within recency window
    within_window = bool(posted_at) and (datetime.now(timezone.utc) - posted_at).days <= _METRIC_RECENCY_DAYS
    metrics = {}
    if within_window:
        try:
            metrics = get_ig_insights(media_id, page_token)
        except Exception as e:
            log.info("ig insights failed for %s: %s", media_id, e)

    tags = _extract_hashtags(caption)
    _upsert_post(
        tenant_id=tenant_id, connection_id=connection_id, platform="instagram",
        post_ref=media_id, permalink=permalink, posted_at=posted_at,
        post_type=post_type, caption=caption, tags=tags, metrics=metrics,
    )


def _upsert_and_poll_fb(
    *, tenant_id, connection_id, post: dict[str, Any], page_token: str,
):
    from meta_client import get_page_post_insights
    from datetime import datetime as _dt
    post_id = post.get("id")
    caption = post.get("message") or ""
    permalink = post.get("permalink_url")
    posted_at_raw = post.get("created_time")
    posted_at = None
    if posted_at_raw:
        try:
            posted_at = _dt.fromisoformat(posted_at_raw.replace("Z", "+00:00"))
        except Exception:
            pass
    within_window = bool(posted_at) and (datetime.now(timezone.utc) - posted_at).days <= _METRIC_RECENCY_DAYS
    metrics = {}
    if within_window:
        try:
            metrics = get_page_post_insights(post_id, page_token)
        except Exception as e:
            log.info("fb insights failed for %s: %s", post_id, e)
    tags = _extract_hashtags(caption)
    _upsert_post(
        tenant_id=tenant_id, connection_id=connection_id, platform="facebook",
        post_ref=post_id, permalink=permalink, posted_at=posted_at,
        post_type="feed", caption=caption, tags=tags, metrics=metrics,
    )


def _upsert_post(
    *, tenant_id, connection_id, platform: str, post_ref: str,
    permalink: str | None, posted_at, post_type: str,
    caption: str, tags: list[str], metrics: dict,
):
    import json as _json
    with tenant_connection(tenant_id) as conn:
        # Upsert the post row itself
        conn.execute(
            "INSERT INTO social_posts "
            "(tenant_id, connection_id, platform, post_ref, permalink, posted_at, "
            "post_type, caption, tags, metrics, metrics_history, last_polled_at, origin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
            "COALESCE((SELECT metrics_history FROM social_posts WHERE tenant_id=%s "
            "AND platform=%s AND post_ref=%s), '[]'::jsonb), now(), 'watched') "
            "ON CONFLICT (tenant_id, platform, post_ref) DO UPDATE SET "
            "caption = EXCLUDED.caption, tags = EXCLUDED.tags, "
            "permalink = COALESCE(EXCLUDED.permalink, social_posts.permalink), "
            "metrics = EXCLUDED.metrics, "
            "metrics_history = social_posts.metrics_history || jsonb_build_array(EXCLUDED.metrics), "
            "last_polled_at = now()",
            (str(tenant_id), str(connection_id), platform, post_ref, permalink,
             posted_at, post_type, caption[:5000], tags, _json.dumps(metrics),
             str(tenant_id), platform, post_ref),
        )


def _extract_hashtags(caption: str) -> list[str]:
    import re
    if not caption:
        return []
    return [t.lower() for t in re.findall(r"#(\w{2,50})", caption)[:20]]
