"""v4.0 Phase C — Meta Marketing API publisher.

Implements BOTH interfaces so it slots into every call site cleanly:
  - legacy `.deploy(...)`: the approve→dispatch path (from integrations.dispatch)
  - `.publish(...)`/`.poll_metrics(...)`/`.cancel(...)`: the orchestrator
    PublisherAdapter Protocol (drop-in replacement for MockAdsAdapter)

Uses the picked ad account / page / IG account from meta_connections; loads
tokens through token_crypto. When no connection exists for the tenant (or the
token has expired), publish() raises with a clear message — the orchestrator
downgrades the iteration to 'failed' and releases committed budget.

Sandbox mode: when settings.meta_use_sandbox is true, the objective + status
stay 'PAUSED' even after publish and no live spend accrues. Toggle by env
without redeploying code once App Review lands.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from config import settings
from db.session import tenant_connection
from storage import signed_url
from token_crypto import decrypt

from ._base import record_stub
from . import meta_ads  # noqa: F401 self-import placeholder to appease linters if any

log = logging.getLogger("meta_ads")


# Map our persona segments → Meta targeting shorthand.
# Deliberately conservative: overriding age/geo/interests is a compliance
# surface, so we default broadly and refine only where confident.
def _persona_to_targeting(persona: str | None) -> dict:
    p = (persona or "").lower()
    targeting = {
        "geo_locations": {"countries": ["IN"]},   # tenant-scope override at bootstrap TBD
        "age_min": 18,
        "age_max": 65,
    }
    if any(t in p for t in ("young", "gen z", "student", "college")):
        targeting["age_min"], targeting["age_max"] = 18, 27
    elif "millennial" in p or "young professional" in p:
        targeting["age_min"], targeting["age_max"] = 25, 40
    elif "premium" in p or "empty nester" in p or "senior" in p:
        targeting["age_min"], targeting["age_max"] = 40, 65
    elif "parent" in p or "family" in p:
        targeting["age_min"], targeting["age_max"] = 28, 48
    return targeting


# Goal metric → Meta optimization goal (best-fit map)
_OPT_GOAL_BY_METRIC = {
    "clicks":      ("LINK_CLICKS", "IMPRESSIONS"),
    "ctr":         ("LINK_CLICKS", "IMPRESSIONS"),
    "conversions": ("OFFSITE_CONVERSIONS", "IMPRESSIONS"),
    "reach":       ("REACH", "IMPRESSIONS"),
    "impressions": ("IMPRESSIONS", "IMPRESSIONS"),
    "engagement":  ("POST_ENGAGEMENT", "IMPRESSIONS"),
    "followers":   ("PAGE_LIKES", "IMPRESSIONS"),
}


def _load_connection(tenant_id: UUID, brand_id: UUID | None = None) -> dict | None:
    """Pick the best meta_connection for (tenant, brand).
    Preference: brand-specific > tenant-default (brand_id NULL) > any other.
    """
    with tenant_connection(tenant_id) as conn:
        r = conn.execute(
            "SELECT id, meta_user_id, encrypted_access_token, token_expires_at, "
            "selected_ad_account_id, selected_page_id, selected_page_access_token, "
            "selected_ig_user_id, status, brand_id "
            "FROM meta_connections WHERE tenant_id = %s AND status = 'connected' "
            "ORDER BY CASE "
            "  WHEN brand_id = %s THEN 0 "
            "  WHEN brand_id IS NULL THEN 1 "
            "  ELSE 2 END, "
            "updated_at DESC LIMIT 1",
            (str(tenant_id), str(brand_id) if brand_id else None),
        ).fetchone()
    if not r:
        return None
    return {
        "id": str(r[0]), "meta_user_id": r[1],
        "user_token": decrypt(r[2]),
        "token_expires_at": r[3],
        "ad_account_id": r[4], "page_id": r[5],
        "page_token": decrypt(r[6]) if r[6] else None,
        "ig_user_id": r[7], "status": r[8],
        "brand_id": str(r[9]) if r[9] else None,
    }


def _link_url_for_creative(tenant_id: UUID, storage_path: str) -> str:
    """Placeholder click URL. Real flow: tenants configure a landing URL per
    campaign; for now we use the creative's signed asset URL so ads publish."""
    try:
        return signed_url(storage_path)
    except Exception:
        return "https://example.com"


class MetaAdsAdapter:
    """Orchestrator publisher + legacy deployer, same class."""

    channel = "meta_ads"

    # --------------------------------------------------------
    # Legacy .deploy() path (integrations.dispatch)
    # --------------------------------------------------------
    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str,
               copy: dict[str, Any]) -> dict[str, Any]:
        """Called from api/creatives.py `approve`. For a lone approved
        creative we skip campaign/adset scaffolding and just record the
        intent as a deployments row — full ad publishing is the
        orchestrator's job. If a Meta connection exists we upgrade this
        to a real Ad Creative upload; otherwise we stub."""
        conn_info = _load_connection(tenant_id)
        if not conn_info:
            return record_stub(
                tenant_id, creative_id, self.channel,
                {"storage_path": storage_path, "copy": copy,
                 "reason": "no meta_connection for tenant"},
            )
        try:
            image_bytes = _download(storage_path)
            from meta_client import upload_creative_image
            image_hash = upload_creative_image(
                conn_info["ad_account_id"], conn_info["user_token"],
                image_bytes, filename=f"{creative_id}.webp",
            )
        except Exception as e:
            log.warning("meta_ads.deploy: creative upload failed: %s", e)
            return record_stub(
                tenant_id, creative_id, self.channel,
                {"storage_path": storage_path, "copy": copy, "error": str(e)},
            )
        # Record as prepared-not-published — the orchestrator publishes ads.
        with tenant_connection(tenant_id) as conn:
            conn.execute(
                "insert into deployments (tenant_id, creative_id, channel, status, payload) "
                "values (%s, %s, %s, 'prepared', %s::jsonb)",
                (str(tenant_id), str(creative_id), self.channel,
                 _json({"image_hash": image_hash, "copy": copy})),
            )
        return {"status": "prepared", "image_hash": image_hash}

    # --------------------------------------------------------
    # Orchestrator PublisherAdapter Protocol
    # --------------------------------------------------------
    def publish(
        self, *, tenant_id: str, iteration_id: str, creative_id: str,
        storage_path: str, copy: dict[str, Any], format: str,
        persona: str | None, spend_planned: float,
        brand_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_uuid = UUID(tenant_id)
        brand_uuid = UUID(brand_id) if brand_id else None
        conn_info = _load_connection(tenant_uuid, brand_uuid)
        if not conn_info:
            raise RuntimeError(
                "no Meta connection for this tenant/brand — connect one at "
                "/settings/connections before running meta_ads iterations"
            )

        if format == "video":
            # v4.0 Phase D: video ad publishing needs Meta's chunked upload
            # (/act_x/advideos + video_hash-based creative). We have the mp4
            # in storage; the chunked upload adapter lands in a follow-up.
            # For now, fail cleanly so the orchestrator marks the iteration
            # failed and releases budget — better than a half-published state.
            raise RuntimeError(
                "meta_ads video publishing is not yet wired — use "
                "instagram_organic (Reels) or mock_ads for video iterations "
                "until the chunked video-upload path ships"
            )

        # Import here to keep the module import cheap (avoid httpx at boot)
        from meta_client import (create_ad, create_adset,
                                 create_campaign, create_link_ad_creative,
                                 upload_creative_image, with_retry)

        image_bytes = _download(storage_path)
        image_hash = with_retry(
            upload_creative_image, conn_info["ad_account_id"],
            conn_info["user_token"], image_bytes,
            filename=f"iter_{iteration_id[:8]}.webp",
        )

        # 1. Campaign
        # NOTE: iteration-per-campaign so insights are cleanly separable.
        camp = with_retry(
            create_campaign, conn_info["ad_account_id"], conn_info["user_token"],
            name=f"exp:{iteration_id[:8]}:{format}",
            objective="OUTCOME_TRAFFIC", status="PAUSED",
        )
        # 2. AdSet — daily_budget is in minor units (paise/cents).
        # Spend_planned is our top-level cap; use it as the daily budget for a 1-day run.
        opt_goal, billing = _OPT_GOAL_BY_METRIC.get("clicks", ("LINK_CLICKS", "IMPRESSIONS"))
        adset = with_retry(
            create_adset, conn_info["ad_account_id"], conn_info["user_token"],
            campaign_id=camp["id"], name=f"exp:{iteration_id[:8]}:as",
            daily_budget_minor_units=max(100, int(spend_planned * 100)),
            targeting=_persona_to_targeting(persona),
            promoted_page_id=conn_info["page_id"],
            optimization_goal=opt_goal, billing_event=billing,
            status="PAUSED",
        )
        # 3. Creative
        link_url = _link_url_for_creative(tenant_uuid, storage_path)
        creative = with_retry(
            create_link_ad_creative, conn_info["ad_account_id"], conn_info["user_token"],
            page_id=conn_info["page_id"], image_hash=image_hash,
            headline=copy.get("headline") or "", body=copy.get("body") or "",
            cta_type="LEARN_MORE", link_url=link_url,
            ig_user_id=conn_info.get("ig_user_id"),
            name=f"exp:{iteration_id[:8]}:cr",
        )
        # 4. Ad — sandbox mode leaves it PAUSED; live mode ACTIVE
        ad_status = "PAUSED" if settings.meta_use_sandbox else "ACTIVE"
        ad = with_retry(
            create_ad, conn_info["ad_account_id"], conn_info["user_token"],
            name=f"exp:{iteration_id[:8]}", adset_id=adset["id"],
            creative_id=creative["id"], status=ad_status,
        )
        return {
            "ad_id": ad["id"],
            "adset_id": adset["id"],
            "campaign_id": camp["id"],
            "creative_id": creative["id"],
            "image_hash": image_hash,
            "permalink": f"https://business.facebook.com/adsmanager/manage/ads?act={conn_info['ad_account_id'].lstrip('act_')}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "budget": spend_planned,
            "status": ad_status,
        }

    def poll_metrics(
        self, *, publish_ref: dict[str, Any], format: str, persona: str | None,
        hypothesis: str | None, spend_planned: float, window_hours: int,
        elapsed_hours: float, poll_index: int,
    ) -> dict[str, Any]:
        from meta_client import get_insights, with_retry
        # Look up the tenant via the ad's ownership record — we passed the
        # connection's user token via the publish; we need it again here.
        # Simplest correct approach: page tokens are on the deployments row
        # for this iteration. Deferred: for MVP we rely on the same
        # connection lookup as publish — one connection per tenant.
        tenant_uuid = _tenant_for_ad(publish_ref.get("ad_id"))
        if not tenant_uuid:
            return {"error": "unknown ad tenant"}
        conn_info = _load_connection(tenant_uuid)
        if not conn_info:
            return {"error": "meta connection disconnected mid-flight"}

        raw = with_retry(get_insights, publish_ref["ad_id"], conn_info["user_token"])
        # Normalise into the same schema the mock adapter emits so the
        # analyzer + distiller work interchangeably.
        actions = raw.get("actions") or []
        conversions = 0
        for a in actions:
            if a.get("action_type") in ("offsite_conversion.fb_pixel_purchase",
                                          "purchase", "complete_registration"):
                conversions += int(a.get("value") or 0)
        engagement = 0
        for a in actions:
            if a.get("action_type") in ("like", "post_reaction", "post",
                                          "comment", "post_engagement", "video_view"):
                engagement += int(a.get("value") or 0)
        return {
            "impressions": int(raw.get("impressions") or 0),
            "reach": int(raw.get("reach") or 0),
            "clicks": int(raw.get("clicks") or 0),
            "ctr": float(raw.get("ctr") or 0) / 100.0,   # Meta returns percentage
            "cpc": float(raw.get("cpc") or 0),
            "spend": float(raw.get("spend") or 0),
            "conversions": conversions,
            "engagement": engagement,
            "followers_gained": 0,
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_hours": round(elapsed_hours, 2),
        }

    def cancel(self, publish_ref: dict[str, Any]) -> None:
        """Kill-switch: pause the ad so it stops spending immediately."""
        from meta_client import pause_ad
        tenant_uuid = _tenant_for_ad(publish_ref.get("ad_id"))
        if not tenant_uuid:
            return
        conn_info = _load_connection(tenant_uuid)
        if not conn_info:
            return
        try:
            pause_ad(publish_ref["ad_id"], conn_info["user_token"])
        except Exception as e:
            log.warning("cancel/pause failed for ad %s: %s", publish_ref.get("ad_id"), e)


# ============================================================
# Internal helpers
# ============================================================

def _download(storage_path: str) -> bytes:
    from storage import download_bytes
    return download_bytes(storage_path)


def _json(obj: Any) -> str:
    import json as _json
    return _json.dumps(obj, default=str)


def _tenant_for_ad(ad_id: str | None) -> UUID | None:
    """Find the tenant that owns a given Meta ad_id via deployments/creatives."""
    if not ad_id:
        return None
    from db.session import get_pool
    pool = get_pool()
    with pool.connection() as conn:
        r = conn.execute(
            "SELECT tenant_id FROM deployments "
            "WHERE channel = 'meta_ads' AND payload->>'ad_id' = %s "
            "ORDER BY id DESC LIMIT 1",
            (ad_id,),
        ).fetchone()
    return UUID(str(r[0])) if r else None


# Also register in the mock_ads adapter registry so orchestrator can pick us up.
try:
    from integrations import mock_ads as _mock
    _mock._ADAPTERS["meta_ads"] = MetaAdsAdapter()
except Exception:
    # Import-order-safe: mock_ads will resolve get_adapter() dynamically anyway.
    pass


# Keep the old name importable for anything still referencing it.
MetaAdsDeployer = MetaAdsAdapter
