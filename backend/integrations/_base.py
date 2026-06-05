"""Shared stub helper — writes a deployments row with status='stubbed'."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from db.session import tenant_connection

log = logging.getLogger("integrations")


def record_stub(tenant_id: UUID, creative_id: UUID, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    log.info("[STUB DEPLOY] channel=%s creative=%s payload=%s", channel, creative_id, payload)
    with tenant_connection(tenant_id) as conn:
        conn.execute(
            "insert into deployments (tenant_id, creative_id, channel, status, payload) "
            "values (%s, %s, %s, 'stubbed', %s::jsonb)",
            (str(tenant_id), str(creative_id), channel, json.dumps(payload)),
        )
    return {"status": "stubbed", "channel": channel}
