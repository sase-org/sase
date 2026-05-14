"""Runtime status and gate reporting for daemon rollout diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.daemon.rollout_gates import GateCoverage, evaluate_milestone_coverage
from sase.daemon.rollout_registry import RolloutSurfaceRecord
from sase.daemon._rollout_diagnostics_utils import (
    collect_string_list,
    mapping,
    reported_gate_value,
    reported_set,
)
from sase.integrations._daemon_lifecycle_types import DaemonInspection


def compatibility_status(inspection: DaemonInspection) -> dict[str, Any]:
    if inspection.state != "running":
        return {
            "status": "unavailable",
            "message": "daemon is not running",
            "details": None,
        }
    rpc = inspection.rpc if isinstance(inspection.rpc, dict) else {}
    if not rpc.get("available"):
        message = str(rpc.get("message") or "health RPC unavailable")
        lowered = message.lower()
        status = (
            "incompatible"
            if any(
                token in lowered for token in ("unsupported", "schema", "incompatible")
            )
            else "unavailable"
        )
        return {"status": status, "message": message, "details": None}
    health = mapping(rpc.get("health"))
    compatibility = mapping(health.get("compatibility"))
    if not compatibility:
        return {
            "status": "not_reported",
            "message": "daemon health did not report compatibility fields",
            "details": None,
        }
    return {
        "status": "ok",
        "message": "client, daemon, and projection schemas are compatible",
        "details": compatibility,
    }


def observed_capabilities(inspection: DaemonInspection) -> frozenset[str]:
    rpc = inspection.rpc if isinstance(inspection.rpc, dict) else {}
    health = mapping(rpc.get("health"))
    details = mapping(health.get("details"))
    capabilities: set[str] = set()
    collect_string_list(capabilities, health.get("capabilities"))
    collect_string_list(capabilities, health.get("declared_capabilities"))
    collect_string_list(capabilities, details.get("capabilities"))
    capabilities_payload = mapping(details.get("capability_advertisement"))
    collect_string_list(capabilities, capabilities_payload.get("capabilities"))
    return frozenset(capabilities)


def gate_coverage(
    report: Mapping[str, Any] | None,
    *,
    observed_capabilities: frozenset[str],
    compatibility_ok: bool,
) -> GateCoverage:
    contract_snapshots = reported_set(report, "contract_snapshots")
    if compatibility_ok:
        contract_snapshots = frozenset({*contract_snapshots, "local_daemon.v1"})
    return GateCoverage(
        capabilities=frozenset(
            {*observed_capabilities, *reported_set(report, "capabilities")}
        ),
        contract_snapshots=contract_snapshots,
        parity_gates=reported_set(report, "parity_gates"),
        perf_gates=reported_set(report, "perf_gates"),
        recovery_checks=reported_set(report, "recovery_checks"),
        docs_links=reported_set(report, "docs_links"),
    )


def milestone_payloads(coverage: GateCoverage) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for status in evaluate_milestone_coverage(coverage):
        payloads.append(
            {
                "milestone": status.milestone,
                "covered": status.covered,
                "missing_by_kind": {
                    kind.value: list(missing)
                    for kind, missing in status.missing_by_kind.items()
                },
            }
        )
    return payloads


def parity_status(
    record: RolloutSurfaceRecord,
    inspection: DaemonInspection,
) -> dict[str, Any]:
    if not record.parity_gates:
        return {"status": "not_required", "gates": []}
    if inspection.state != "running":
        return {
            "status": "unavailable",
            "gates": list(record.parity_gates),
            "message": "daemon is not running",
        }
    rpc = inspection.rpc if isinstance(inspection.rpc, dict) else {}
    health = mapping(rpc.get("health"))
    details = mapping(health.get("details"))
    indexing = mapping(details.get("indexing"))
    projection = mapping(details.get("projection_db"))
    state = str(indexing.get("state") or projection.get("state") or "not_reported")
    message = str(indexing.get("message") or projection.get("message") or "")
    return {"status": state, "gates": list(record.parity_gates), "message": message}


def perf_status(
    record: RolloutSurfaceRecord,
    report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not record.perf_gates:
        return {"status": "not_required", "gates": []}
    if report is None:
        return {"status": "not_reported", "gates": list(record.perf_gates)}
    gate_payloads = []
    for gate in record.perf_gates:
        value = reported_gate_value(report, gate)
        if value is None:
            gate_payloads.append({"gate": gate, "status": "missing"})
        elif isinstance(value, Mapping):
            gate_payloads.append({"gate": gate, **dict(value)})
        else:
            gate_payloads.append({"gate": gate, "status": str(value)})
    overall = (
        "ok" if all(item.get("status") == "ok" for item in gate_payloads) else "blocked"
    )
    return {"status": overall, "gates": gate_payloads}


def fallback_command(record: RolloutSurfaceRecord, mode: object) -> str | None:
    if not record.direct_fallback_available:
        return None
    if record.family == "read":
        return "SASE_NO_DAEMON=1"
    if record.family == "write":
        return "SASE_NO_DAEMON=1"
    if record.family == "scheduler":
        key = record.config_keys[0] if record.config_keys else ""
        env = {
            "daemon.scheduler.launch_mode": "SASE_DAEMON_SCHEDULER_LAUNCH_MODE",
            "daemon.scheduler.lifecycle_mode": "SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE",
            "daemon.scheduler.axe_mode": "SASE_DAEMON_SCHEDULER_AXE_MODE",
        }.get(key)
        return f"{env}=direct" if env else "SASE_NO_DAEMON=1"
    if record.family == "provider_host":
        return "SASE_PROVIDER_HOST_MODE=direct"
    if str(mode) == "disabled":
        return None
    return "SASE_NO_DAEMON=1"


__all__ = [
    "compatibility_status",
    "fallback_command",
    "gate_coverage",
    "milestone_payloads",
    "observed_capabilities",
    "parity_status",
    "perf_status",
]
