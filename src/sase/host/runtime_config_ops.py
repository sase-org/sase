"""Config/fake operation handlers for the provider host runtime."""

from __future__ import annotations

import importlib.metadata
import sys
import time
from collections.abc import Mapping
from typing import Any

from sase.host.manifest import (
    discover_host_manifests,
    resource_policy_diagnostics,
)
from sase.host.routing import host_routing_diagnostics
from sase.host.runtime_shared import (
    OperationContext,
    ProviderHostRuntimeError,
    redact_host_log,
)


def fake_echo(context: OperationContext) -> Mapping[str, Any]:
    context.logs.append("info", "fake echo operation dispatched", target="sase.host")
    return {
        "echo": dict(context.request.payload),
        "operation": context.request.operation.operation,
        "request_id": context.request.request_id,
    }


def fake_log(context: OperationContext) -> Mapping[str, Any]:
    message = str(context.request.payload.get("message", "fake log"))
    context.logs.append("info", message, target="sase.host.fake")
    return {"logged": True}


def fake_stderr(context: OperationContext) -> Mapping[str, Any]:
    message = str(context.request.payload.get("message", "fake stderr"))
    context.logs.append("warn", message, target="sase.host.fake", stream="stderr")
    print(redact_host_log(message), file=sys.stderr, flush=True)
    return {"stderr": True}


def fake_sleep(context: OperationContext) -> Mapping[str, Any]:
    sleep_ms = int(context.request.payload.get("sleep_ms", 0))
    if sleep_ms < 0:
        raise ProviderHostRuntimeError(
            "host_protocol_error",
            "sleep_ms must be non-negative",
            target="payload.sleep_ms",
        )
    context.logs.append("info", f"sleeping for {sleep_ms}ms", target="sase.host.fake")
    deadline_ms = (
        context.request.deadline.timeout_ms or context.config.default_timeout_ms
    )
    if sleep_ms > deadline_ms:
        time.sleep(deadline_ms / 1000)
        raise ProviderHostRuntimeError(
            "host_timeout",
            f"fake sleep exceeded timeout of {deadline_ms}ms",
            retryable=True,
            target=context.request.request_id,
        )
    time.sleep(sleep_ms / 1000)
    return {"slept_ms": sleep_ms}


def discover_plugins(context: OperationContext) -> Mapping[str, Any]:
    groups = (
        "sase_llm",
        "sase_vcs",
        "sase_workspace",
        "sase_config",
        "sase_xprompts",
    )
    discovered: dict[str, list[dict[str, str]]] = {}
    entry_points = importlib.metadata.entry_points()
    for group in groups:
        discovered[group] = [
            {"name": ep.name, "value": ep.value}
            for ep in sorted(
                entry_points.select(group=group), key=lambda item: item.name
            )
        ]
    discovery = discover_host_manifests(
        entry_points={
            group: tuple(item["name"] for item in items)
            for group, items in discovered.items()
        }
    )
    context.logs.append(
        "info",
        "plugin entry points and host manifests discovered",
        target="sase.host",
    )
    return {
        "entry_points": discovered,
        "manifests": [
            {
                "plugin_id": record.manifest.plugin_id,
                "operation_families": list(record.manifest.operation_families),
                "network_mode": record.manifest.network.mode,
                "compatibility_mode": record.compatibility_mode,
                "source": record.source,
                "daemon_authoritative": record.daemon_authoritative,
            }
            for record in discovery.records
        ],
        "manifest_diagnostics": list(discovery.diagnostics),
        "resource_policy": resource_policy_diagnostics(),
        "routing": host_routing_diagnostics(),
    }
