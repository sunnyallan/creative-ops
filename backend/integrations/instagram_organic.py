"""v4.0 Phase C — Instagram organic publisher.

Publishes to the connected IG Business account via the Content Publishing API.
IG requires images to be reachable via a public URL, so we use Supabase
signed URLs (already 1h+ TTL). Carousels build multiple item containers first
then a parent carousel container, then publish once.

Same PublisherAdapter Protocol as mock_ads / meta_ads — orchestrator picks
this up when a channel is 'instagram_organic'.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from db.session import tenant_connection
from storage import signed_url
from token_crypto import decrypt

log = logging.getLogger("instagram_organic")


def _load_ig_connection(tenant_id: UUID) -> dict | None:
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT id, selected_ig_user_id, selected_page_access_token, selected_page_id "
            "FROM meta_connections WHERE tenant_id = %s AND status = 'connected' "
            "AND selected_ig_user_id IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 1",
            (str(tenant_id),),
        ).fetchone()
    if not r:
        return None
    return {
        "id": str(r[0]),
        "ig_user_id": r[1],
        "page_token": decrypt(r[2]) if r[2] else None,
        "page_id": r[3],
    }


def _wait_for_container_ready(container_id: str, page_token: str,
                              timeout_seconds: int = 30) -> None:
    """IG containers take a moment to process. Poll status_code up to a timeout."""
    from meta_client import _base
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{_base()}/{container_id}", params={
                "fields": "status_code", "access_token": page_token,
            })
        if r.status_code == 200:
            code = (r.json() or {}).get("status_code")
            if code == "FINISHED":
                return
            if code == "ERROR":
                raise RuntimeError(f"IG container {container_id} errored")
        time.sleep(1.0)
    log.warning("IG container %s not FINISHED after %ss; publishing anyway",
                container_id, timeout_seconds)


class InstagramOrganicAdapter:
    channel = "instagram_organic"

    def publish(
        self, *, tenant_id: str, iteration_id: str, creative_id: str,
        storage_path: str, copy: dict[str, Any], format: str,
        persona: str | None, spend_planned: float,
    ) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        conn_info = _load_ig_connection(tenant_uuid)
        if not conn_info:
            raise RuntimeError(
                "no Instagram Business account connected — link one at /settings/connections"
            )

        from meta_client import (create_ig_media_container, publish_ig_media,
                                 with_retry)

        image_url = signed_url(storage_path)
        caption = " ".join(x for x in [copy.get("headline"), copy.get("body"),
                                        copy.get("cta")] if x) or ""

        container = with_retry(
            create_ig_media_container,
            conn_info["ig_user_id"], conn_info["page_token"],
            image_url=image_url, caption=caption,
        )
        _wait_for_container_ready(container["id"], conn_info["page_token"])
        published = with_retry(
            publish_ig_media,
            conn_info["ig_user_id"], conn_info["page_token"],
            container["id"],
        )
        media_id = published["id"]

        # Record into social_posts (also read by the watcher for metric polling)
        with tenant_connection(tenant_uuid) as conn:
            conn.execute(
                "insert into social_posts (tenant_id, brand_id, platform, post_ref, "
                "posted_at, post_type, caption, creative_id, connection_id, origin) "
                "values (%s, NULL, 'instagram', %s, now(), 'feed', %s, %s, %s, 'authored') "
                "on conflict (tenant_id, platform, post_ref) do nothing",
                (str(tenant_uuid), media_id, caption[:2200],
                 str(creative_id), conn_info["id"]),
            )

        return {
            "media_id": media_id,
            "container_id": container["id"],
            "permalink": f"https://www.instagram.com/p/{media_id}/",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "budget": 0.0,   # organic
        }

    def poll_metrics(
        self, *, publish_ref: dict[str, Any], format: str, persona: str | None,
        hypothesis: str | None, spend_planned: float, window_hours: int,
        elapsed_hours: float, poll_index: int,
    ) -> dict[str, Any]:
        from meta_client import get_ig_insights, with_retry
        # Locate the tenant via social_posts (unique by post_ref)
        from db.session import get_pool
        media_id = publish_ref.get("media_id")
        if not media_id:
            return {"error": "no media_id"}
        pool = get_pool()
        with pool.connection() as conn:
            r = conn.execute(
                "SELECT tenant_id FROM social_posts "
                "WHERE platform='instagram' AND post_ref = %s LIMIT 1",
                (media_id,),
            ).fetchone()
        if not r:
            return {"error": "post row not found"}
        tenant_uuid = UUID(str(r[0]))
        conn_info = _load_ig_connection(tenant_uuid)
        if not conn_info:
            return {"error": "instagram disconnected"}
        raw = with_retry(get_ig_insights, media_id, conn_info["page_token"])
        return {
            "impressions": int(raw.get("impressions") or 0),
            "reach": int(raw.get("reach") or 0),
            "clicks": 0,                       # organic IG has no clicks metric
            "ctr": 0.0, "cpc": 0.0, "spend": 0.0,
            "conversions": 0,
            "engagement": int(raw.get("engagement") or 0),
            "likes": int(raw.get("likes") or 0),
            "comments": int(raw.get("comments") or 0),
            "shares": int(raw.get("shares") or 0),
            "saves": int(raw.get("saved") or 0),
            "followers_gained": int(raw.get("follows") or 0),
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_hours": round(elapsed_hours, 2),
        }

    def cancel(self, publish_ref: dict[str, Any]) -> None:
        """Organic posts can't be 'paused' — leaving them up is correct
        behaviour. If the user really wants it gone they can delete it
        from IG. No-op here matches user expectation for organic loops."""
        log.info("instagram_organic cancel is a no-op for media %s",
                 publish_ref.get("media_id"))


try:
    from integrations import mock_ads as _mock
    _mock._ADAPTERS["instagram_organic"] = InstagramOrganicAdapter()
except Exception:
    pass
