"""Google Ads deployer — STUB.

Real impl: use google-ads-python to create a ResponsiveDisplayAd asset and
attach to an ad group. Requires developer token + MCC + OAuth refresh token.
Phase 3 in the architecture doc.
"""
from typing import Any
from uuid import UUID

from ._base import record_stub


class GoogleAdsDeployer:
    channel = "google_display"

    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]:
        return record_stub(
            tenant_id, creative_id, self.channel,
            {"storage_path": storage_path, "copy": copy, "todo": "google_ads_api"},
        )
