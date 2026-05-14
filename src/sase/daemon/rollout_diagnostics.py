"""User-facing daemon rollout diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.config.core import load_config_without_plugin_defaults
from sase.daemon.rollout_registry import RolloutSurfaceRecord, rollout_surface_records
from sase.daemon._rollout_diagnostics_modes import effective_mode, top_level_state
from sase.daemon._rollout_diagnostics_release import (
    provider_host_payload,
    release_checklist_payload,
)
from sase.daemon._rollout_diagnostics_status import (
    compatibility_status,
    fallback_command,
    gate_coverage,
    milestone_payloads,
    observed_capabilities,
    parity_status,
    perf_status,
)
from sase.daemon._rollout_diagnostics_utils import (
    load_json_report,
    mapping,
    missing_count,
    mode_needs_daemon,
    source_label,
)
from sase.integrations._daemon_lifecycle_types import DaemonInspection


def rollout_diagnostics_payload(
    inspection: DaemonInspection,
    *,
    args: Any | None = None,
    benchmark_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build rollout diagnostics for CLI and release automation."""

    config = load_config_without_plugin_defaults()
    benchmark_report = load_json_report(benchmark_report_path)
    observed_capability_set = observed_capabilities(inspection)
    compatibility = compatibility_status(inspection)
    coverage = gate_coverage(
        benchmark_report,
        observed_capabilities=observed_capability_set,
        compatibility_ok=compatibility["status"] == "ok",
    )
    top_level = top_level_state(args)
    surfaces = [
        _surface_payload(
            record,
            args=args,
            config=config,
            inspection=inspection,
            observed_capabilities=observed_capability_set,
            benchmark_report=benchmark_report,
            top_level_disabled=bool(top_level["disabled"]),
        )
        for record in rollout_surface_records()
    ]

    return {
        "schema_version": 1,
        "daemon": {
            "state": inspection.state,
            "message": inspection.message,
            "run_root": str(inspection.paths.run_root),
            "socket_path": str(inspection.paths.socket_path),
            "rpc_available": bool(
                isinstance(inspection.rpc, dict) and inspection.rpc.get("available")
            ),
        },
        "top_level": top_level,
        "capabilities": {
            "status": "reported" if observed_capability_set else "unavailable",
            "observed": sorted(observed_capability_set),
        },
        "compatibility": compatibility,
        "provider_host": provider_host_payload(),
        "milestones": milestone_payloads(coverage),
        "surfaces": surfaces,
        "release_checklist": release_checklist_payload(
            config,
            coverage,
            surfaces=surfaces,
        ),
        "benchmark_report": {
            "path": str(benchmark_report_path) if benchmark_report_path else None,
            "loaded": benchmark_report is not None,
        },
    }


def print_rollout_diagnostics(payload: Mapping[str, Any]) -> None:
    """Print concise human-readable rollout diagnostics."""

    daemon = mapping(payload.get("daemon"))
    top_level = mapping(payload.get("top_level"))
    caps = mapping(payload.get("capabilities"))
    compatibility = mapping(payload.get("compatibility"))

    print(f"SASE daemon rollout: {daemon.get('state', 'unknown')}")
    if daemon.get("message"):
        print(f"Detail: {daemon['message']}")
    print(
        "Top-level daemon: {state} ({source})".format(
            state="disabled" if top_level.get("disabled") else "enabled",
            source=source_label(mapping(top_level.get("source"))),
        )
    )
    observed = caps.get("observed")
    if isinstance(observed, list) and observed:
        print(f"Capabilities: {', '.join(str(item) for item in observed)}")
    else:
        print("Capabilities: unavailable")
    print(
        "Compatibility: {status} - {message}".format(
            status=compatibility.get("status", "unknown"),
            message=compatibility.get("message", ""),
        ).rstrip(" -")
    )
    checklist = mapping(payload.get("release_checklist"))
    contract = mapping(checklist.get("supported_schema_ranges"))
    local_daemon = mapping(contract.get("local_daemon"))
    if local_daemon:
        print(
            "Schema range: local_daemon v{min}-v{max}".format(
                min=local_daemon.get("min_supported_schema_version", "?"),
                max=local_daemon.get("max_supported_schema_version", "?"),
            )
        )

    milestones = [
        item for item in payload.get("milestones", []) if isinstance(item, dict)
    ]
    if milestones:
        print("Milestones:")
        for milestone in milestones:
            missing = missing_count(milestone.get("missing_by_kind"))
            state = (
                "covered"
                if milestone.get("covered")
                else f"blocked ({missing} missing)"
            )
            print(f"- {milestone.get('milestone')}: {state}")

    print("Surfaces:")
    for surface in payload.get("surfaces", []):
        if not isinstance(surface, dict):
            continue
        fallback = mapping(surface.get("fallback"))
        source = source_label(mapping(surface.get("mode_source")))
        line = (
            f"- {surface.get('surface_id')}: {surface.get('effective_mode')} "
            f"via {source}"
        )
        blocked = surface.get("blocked_reasons")
        if isinstance(blocked, list) and blocked:
            line += f"; blocked: {blocked[0]}"
        print(line)
        command = fallback.get("command")
        if command:
            print(f"  Fallback: {command}")
        recovery = surface.get("recovery_commands")
        if isinstance(recovery, list) and recovery:
            print(f"  Recovery: {recovery[0]}")


def _surface_payload(
    record: RolloutSurfaceRecord,
    *,
    args: Any | None,
    config: Mapping[str, Any],
    inspection: DaemonInspection,
    observed_capabilities: frozenset[str],
    benchmark_report: Mapping[str, Any] | None,
    top_level_disabled: bool,
) -> dict[str, Any]:
    mode = effective_mode(
        record,
        args=args,
        config=config,
        top_level_disabled=top_level_disabled,
    )
    missing_capabilities = tuple(
        sorted(set(record.daemon_capabilities) - observed_capabilities)
    )
    blocked_reasons = list(mode["blocked_reasons"])
    if mode_needs_daemon(str(mode["mode"])) and inspection.state != "running":
        blocked_reasons.append(f"daemon is {inspection.state}")
    if mode_needs_daemon(str(mode["mode"])) and missing_capabilities:
        blocked_reasons.append(
            "missing daemon capabilities: " + ", ".join(missing_capabilities)
        )
    compatibility = compatibility_status(inspection)
    if mode_needs_daemon(str(mode["mode"])) and compatibility["status"] not in {
        "ok",
        "not_reported",
    }:
        blocked_reasons.append(f"compatibility is {compatibility['status']}")

    return {
        "surface_id": record.surface_id,
        "family": record.family,
        "title": record.title,
        "minimum_milestone": record.minimum_milestone,
        "effective_mode": mode["mode"],
        "mode_source": mode["source"],
        "config_keys": list(record.config_keys),
        "env_overrides": list(record.env_overrides),
        "required_capabilities": list(record.daemon_capabilities),
        "missing_capabilities": list(missing_capabilities),
        "compatibility_status": compatibility["status"],
        "parity_status": parity_status(record, inspection),
        "perf_status": perf_status(record, benchmark_report),
        "fallback": {
            "available": record.direct_fallback_available,
            "command": fallback_command(record, mode["mode"]),
        },
        "recovery_commands": list(record.recovery_commands),
        "default_policy": record.default_policy,
        "default_enablement_allowed": record.default_enablement_allowed,
        "blocked": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
    }


__all__ = [
    "print_rollout_diagnostics",
    "rollout_diagnostics_payload",
]
