"""WhatsApp Business Cloud API deployer — STUB.

Real impl: POST to graph.facebook.com/{phone_number_id}/messages with a
template message carrying the approved banner. Phase 3.
"""
from typing import Any
from uuid import UUID

from ._base import record_stub


class WhatsAppDeployer:
    channel = "whatsapp_banner"

    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]:
        return record_stub(
            tenant_id, creative_id, self.channel,
            {"storage_path": storage_path, "copy": copy, "todo": "whatsapp_cloud_api"},
        )
