"""Platform integrations (Subsystem 6).

For MVP every deployer is stubbed: it writes a row to `deployments` with
status='stubbed' and logs the payload it WOULD have sent. Real implementations
slot in behind the same `Deployer` Protocol without touching the call sites.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import UUID

from .google_ads import GoogleAdsDeployer
from .meta_ads import MetaAdsDeployer
from .whatsapp import WhatsAppDeployer
from .sendgrid import SendGridDeployer

log = logging.getLogger("integrations")


class Deployer(Protocol):
    channel: str
    def deploy(self, tenant_id: UUID, creative_id: UUID, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]: ...


_REGISTRY: dict[str, Deployer] = {
    "google_display": GoogleAdsDeployer(),
    "meta_feed": MetaAdsDeployer(),
    "whatsapp_banner": WhatsAppDeployer(),
    "emailer": SendGridDeployer(),
}


def dispatch(tenant_id: UUID, creative_id: UUID, channel: str, storage_path: str, copy: dict[str, Any]) -> dict[str, Any]:
    dep = _REGISTRY.get(channel)
    if not dep:
        log.warning("no deployer for channel %s", channel)
        return {"status": "no_deployer"}
    return dep.deploy(tenant_id, creative_id, storage_path, copy)
