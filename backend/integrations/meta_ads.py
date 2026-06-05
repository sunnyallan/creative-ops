"""Meta Marketing API deployer — STUB.

Real impl: facebook-business SDK. AdImage → AdCreative → Ad. Needs Business
Verification + App Review for Advanced Access. Phase 3.
"""
from typing import Any
from uuid import UUID

from ._base import record_stub


class MetaAdsDeployer:
    channel = "meta_feed"

    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]:
        return record_stub(
            tenant_id, creative_id, self.channel,
            {"storage_path": storage_path, "copy": copy, "todo": "meta_marketing_api"},
        )
