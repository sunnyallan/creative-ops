"""v4.0 Phase B — Mock ads adapter.

Deterministic-noise ad simulator behind the same PublisherAdapter interface
as the real Meta adapter (Phase C). Lets the full orchestrator loop —
publish → measure → analyze → distill — run end-to-end with zero external
dependencies and zero real spend. Given the same iteration inputs, it
returns the same-shaped metrics (with plausible noise), so learnings
distilled against it are structurally identical to those from real Meta.

Behavioural model (deliberately opinionated so the loop learns *something*
sensible in demos/tests without pretending to be real attribution):
  - carousels beat static by ~15%
  - video beats carousel by ~15% (Reels bias)
  - "young" / "gen z" personas prefer video; "premium" / "empty" prefer static
  - well-formed hypotheses (contain 'learning' or reference a persona) get
    a small confidence-forming boost
  - noise is seeded from (iteration_id + poll_index) so re-polls converge
"""
from __future__ import annotations

import hashlib
import logging
import math
import random
from typing import Any

from datetime import datetime, timezone

log = logging.getLogger("mock_ads")


def _seed_from(*parts: Any) -> random.Random:
    """Deterministic RNG from arbitrary inputs — same inputs → same sequence."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


class MockAdsAdapter:
    """PublisherAdapter Protocol implementation. The orchestrator holds one
    of these per channel; the real adapters (meta_ads, instagram_organic)
    ship in Phase C with the same method signatures."""

    channel = "mock_ads"

    def publish(
        self,
        *,
        tenant_id: str,
        iteration_id: str,
        creative_id: str,
        storage_path: str,
        copy: dict[str, Any],
        format: str,                    # static | carousel | video
        persona: str | None,
        spend_planned: float,
    ) -> dict[str, Any]:
        """Simulate creating a paused ad; return a stable publish_ref."""
        rng = _seed_from("publish", iteration_id)
        pub_ref = {
            "ad_id": f"mock_ad_{rng.randrange(10**10):010d}",
            "adset_id": f"mock_adset_{rng.randrange(10**8):08d}",
            "campaign_id": f"mock_camp_{rng.randrange(10**8):08d}",
            "permalink": f"mock://ads/{iteration_id[:8]}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "budget": spend_planned,
        }
        log.info("[MOCK] published iteration=%s format=%s spend=%.2f ref=%s",
                 iteration_id, format, spend_planned, pub_ref["ad_id"])
        return pub_ref

    def poll_metrics(
        self,
        *,
        publish_ref: dict[str, Any],
        format: str,
        persona: str | None,
        hypothesis: str | None,
        spend_planned: float,
        window_hours: int,
        elapsed_hours: float,
        poll_index: int,
    ) -> dict[str, Any]:
        """Return metrics-so-far. Called every ~15 min by the beat task while
        an iteration is `measuring`. Metrics grow with elapsed_hours, saturate
        near the window end, and vary by format/persona in learnable ways."""
        rng = _seed_from("poll", publish_ref.get("ad_id"), poll_index)

        # 0..1 fraction of the window elapsed, capped
        frac = max(0.0, min(1.0, elapsed_hours / max(1.0, window_hours)))
        # S-curve saturation so the first few polls show meaningful data
        # (1 - e^{-3x}) → ~63% at frac=1/3, ~95% at frac=1
        satur = 1.0 - math.exp(-3.0 * frac)

        # Base impressions scale with spend (CPM-ish ~ 300)
        base_impressions = int((spend_planned / 300.0) * 1000 * satur)
        # Format multiplier: video > carousel > static
        fmt_mult = {"video": 1.32, "carousel": 1.15, "static": 1.0}.get(format, 1.0)
        # Persona interaction (biased on tokens present in the persona string)
        p = (persona or "").lower()
        persona_mult = 1.0
        if format == "video" and any(t in p for t in ("young", "gen z", "student", "college")):
            persona_mult *= 1.20
        if format == "static" and any(t in p for t in ("premium", "empty nesters", "senior")):
            persona_mult *= 1.15
        # Hypothesis quality boost (rewards briefs that reference prior learnings)
        h = (hypothesis or "").lower()
        hyp_mult = 1.05 if ("learning" in h or "prior" in h or persona and p in h) else 1.0

        impressions = int(base_impressions * fmt_mult * persona_mult * hyp_mult)
        # CTR band varies by format; jittered per poll
        ctr_center = {"video": 0.032, "carousel": 0.024, "static": 0.017}.get(format, 0.02)
        ctr = max(0.005, ctr_center * (0.85 + rng.random() * 0.3))
        clicks = int(impressions * ctr)

        # Cost per click ~ CPM/(CTR*1000); spend caps at planned
        cpc = 300.0 / max(1.0, ctr * 1000)
        spend = min(spend_planned, clicks * cpc)

        # Conversion rate: 1.5-3.5% of clicks
        conv_rate = 0.015 + rng.random() * 0.02
        conversions = int(clicks * conv_rate)

        # Engagement (likes+comments+shares+saves) — social-native surfaces
        engagement = int(impressions * (0.008 + rng.random() * 0.006) * fmt_mult)

        # Reach ~ impressions / frequency 1.2
        reach = int(impressions / 1.2)

        return {
            "impressions": impressions,
            "reach": reach,
            "clicks": clicks,
            "ctr": round(ctr, 5),
            "cpc": round(cpc, 4),
            "spend": round(spend, 2),
            "conversions": conversions,
            "engagement": engagement,
            "followers_gained": int(engagement * 0.08),
            "polled_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_hours": round(elapsed_hours, 2),
        }

    def cancel(self, publish_ref: dict[str, Any]) -> None:
        """Kill-switch handler. Real adapters pause the ad; mock is a no-op."""
        log.info("[MOCK] cancel ad=%s", publish_ref.get("ad_id"))


# Registry lookup used by the orchestrator publish node.
_ADAPTERS: dict[str, MockAdsAdapter] = {"mock_ads": MockAdsAdapter()}


def get_adapter(channel: str):
    """Phase C will register meta_ads / instagram_organic here alongside mock_ads."""
    return _ADAPTERS.get(channel) or _ADAPTERS["mock_ads"]
