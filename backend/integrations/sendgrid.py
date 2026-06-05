"""SendGrid emailer deployer — STUB.

Real impl: render HTML email with inline CSS embedding the approved emailer
creative, send via sendgrid-python. Phase 3.
"""
from typing import Any
from uuid import UUID

from ._base import record_stub


class SendGridDeployer:
    channel = "emailer"

    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]:
        return record_stub(
            tenant_id, creative_id, self.channel,
            {"storage_path": storage_path, "copy": copy, "todo": "sendgrid_api"},
        )
