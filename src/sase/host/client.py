"""Client helpers for routed provider/plugin host calls."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient, LocalDaemonError
from sase.daemon.protocol import payload_data
from sase.host.wire import (
    HOST_CAP_IPC_V1,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostResponseEnvelopeWire,
    host_response_from_dict,
)

HOST_ROUTING_DISABLE_ENV = "SASE_DISABLE_PROVIDER_HOST_ROUTING"


class ProviderHostCallUnavailable(RuntimeError):
    """Raised when a host-routed call should fall back to direct Python."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def call_provider_host(
    *,
    family: str,
    operation: str,
    payload: Mapping[str, Any] | None = None,
    required_capability: str,
    timeout_ms: int = 30_000,
    client: LocalDaemonClient | None = None,
) -> HostResponseEnvelopeWire:
    """Call the local daemon provider-host route after capability negotiation."""

    if os.environ.get(HOST_ROUTING_DISABLE_ENV):
        raise ProviderHostCallUnavailable(
            "disabled_by_environment",
            f"{HOST_ROUTING_DISABLE_ENV} is set",
        )

    daemon_client = client or LocalDaemonClient()
    capabilities = _capability_set(daemon_client.capabilities())
    missing = {HOST_CAP_IPC_V1, required_capability} - capabilities
    if missing:
        raise ProviderHostCallUnavailable(
            "unsupported_capability",
            "local daemon does not advertise " + ", ".join(sorted(missing)),
        )

    request = _host_request_payload(
        family=family,
        operation=operation,
        payload=payload or {},
        required_capability=required_capability,
        timeout_ms=timeout_ms,
    )
    response = daemon_client.request({"type": "host_call", "data": request})
    return host_response_from_dict(payload_data(response, "host_call"))


def _host_request_payload(
    *,
    family: str,
    operation: str,
    payload: Mapping[str, Any],
    required_capability: str,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    cwd = Path.cwd()
    return {
        "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        "request_id": f"host_req_{uuid.uuid4().hex}",
        "deadline": {
            "timeout_ms": timeout_ms,
            "deadline_unix_ms": None,
            "cancellation_token": None,
        },
        "actor": {
            "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            "actor_type": "sase-python",
            "name": "sase",
            "version": "0.1.1",
            "runtime": "python",
        },
        "operation": {
            "family": family,
            "operation": operation,
        },
        "declared_capabilities": [HOST_CAP_IPC_V1, required_capability],
        "workspace": {
            "project_id": cwd.name,
            "project_dir": str(cwd),
            "workspace_dir": str(cwd),
            "changespec": None,
        },
        "environment": {
            "inherit": False,
            "allow": [],
            "deny": [],
            "required": [],
        },
        "manifest": None,
        "payload": dict(payload),
    }


def _capability_set(response: dict[str, Any]) -> set[str]:
    capabilities = response.get("capabilities")
    if not isinstance(capabilities, list):
        return set()
    return {item for item in capabilities if isinstance(item, str)}


def is_host_fallbackable(error: Exception) -> bool:
    return isinstance(error, (ProviderHostCallUnavailable, LocalDaemonError))


__all__ = [
    "HOST_ROUTING_DISABLE_ENV",
    "ProviderHostCallUnavailable",
    "call_provider_host",
    "is_host_fallbackable",
]
