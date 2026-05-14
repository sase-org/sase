"""User-facing daemon rollout diagnostics."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sase.config.core import load_config_without_plugin_defaults
from sase.daemon.paths import daemon_disabled
from sase.daemon.rollout_gates import (
    GateCoverage,
    GateKind,
    evaluate_milestone_coverage,
)
from sase.daemon.rollout_registry import (
    TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
    RolloutSurfaceRecord,
    rollout_surface_records,
)
from sase.integrations._daemon_lifecycle_types import DaemonInspection

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

_SCHEDULER_MODE_ALIASES = {
    "off": "direct",
    "false": "direct",
    "0": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "daemon": "daemon_authoritative",
    "daemon_authoritative": "daemon_authoritative",
    "authoritative": "daemon_authoritative",
    "on": "daemon_authoritative",
    "true": "daemon_authoritative",
    "1": "daemon_authoritative",
}

_PROVIDER_HOST_MODE_ALIASES = {
    "0": "direct",
    "false": "direct",
    "off": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "host_preferred": "host_preferred",
    "host-preferred": "host_preferred",
    "preferred": "host_preferred",
    "daemon": "host_preferred",
    "on": "host_preferred",
    "true": "host_preferred",
    "1": "host_preferred",
    "host_required": "host_required",
    "host-required": "host_required",
    "required": "host_required",
}

_LOW_RISK_PROVIDER_HOST_MODES = {
    "llm.metadata": "host_preferred",
    "xprompt.catalog": "host_preferred",
    "vcs.query": "host_preferred",
    "workspace.metadata": "host_preferred",
    "workspace.resolve_ref": "host_preferred",
}


def rollout_diagnostics_payload(
    inspection: DaemonInspection,
    *,
    args: Any | None = None,
    benchmark_report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build rollout diagnostics for CLI and release automation."""

    config = load_config_without_plugin_defaults()
    benchmark_report = _load_json_report(benchmark_report_path)
    observed_capabilities = _observed_capabilities(inspection)
    compatibility = _compatibility_status(inspection)
    coverage = _gate_coverage(
        benchmark_report,
        observed_capabilities=observed_capabilities,
        compatibility_ok=compatibility["status"] == "ok",
    )
    top_level = _top_level_state(args)
    surfaces = [
        _surface_payload(
            record,
            args=args,
            config=config,
            inspection=inspection,
            observed_capabilities=observed_capabilities,
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
            "status": "reported" if observed_capabilities else "unavailable",
            "observed": sorted(observed_capabilities),
        },
        "compatibility": compatibility,
        "milestones": _milestone_payloads(coverage),
        "surfaces": surfaces,
        "benchmark_report": {
            "path": str(benchmark_report_path) if benchmark_report_path else None,
            "loaded": benchmark_report is not None,
        },
    }


def print_rollout_diagnostics(payload: Mapping[str, Any]) -> None:
    """Print concise human-readable rollout diagnostics."""

    daemon = _mapping(payload.get("daemon"))
    top_level = _mapping(payload.get("top_level"))
    caps = _mapping(payload.get("capabilities"))
    compatibility = _mapping(payload.get("compatibility"))

    print(f"SASE daemon rollout: {daemon.get('state', 'unknown')}")
    if daemon.get("message"):
        print(f"Detail: {daemon['message']}")
    print(
        "Top-level daemon: {state} ({source})".format(
            state="disabled" if top_level.get("disabled") else "enabled",
            source=_source_label(_mapping(top_level.get("source"))),
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

    milestones = [
        item for item in payload.get("milestones", []) if isinstance(item, dict)
    ]
    if milestones:
        print("Milestones:")
        for milestone in milestones:
            missing = _missing_count(milestone.get("missing_by_kind"))
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
        fallback = _mapping(surface.get("fallback"))
        source = _source_label(_mapping(surface.get("mode_source")))
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
    mode = _effective_mode(
        record,
        args=args,
        config=config,
        top_level_disabled=top_level_disabled,
    )
    missing_capabilities = tuple(
        sorted(set(record.daemon_capabilities) - observed_capabilities)
    )
    blocked_reasons = list(mode["blocked_reasons"])
    if _mode_needs_daemon(str(mode["mode"])) and inspection.state != "running":
        blocked_reasons.append(f"daemon is {inspection.state}")
    if _mode_needs_daemon(str(mode["mode"])) and missing_capabilities:
        blocked_reasons.append(
            "missing daemon capabilities: " + ", ".join(missing_capabilities)
        )
    compatibility = _compatibility_status(inspection)
    if _mode_needs_daemon(str(mode["mode"])) and compatibility["status"] not in {
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
        "parity_status": _parity_status(record, inspection),
        "perf_status": _perf_status(record, benchmark_report),
        "fallback": {
            "available": record.direct_fallback_available,
            "command": _fallback_command(record, mode["mode"]),
        },
        "recovery_commands": list(record.recovery_commands),
        "default_policy": record.default_policy,
        "default_enablement_allowed": record.default_enablement_allowed,
        "blocked": bool(blocked_reasons),
        "blocked_reasons": blocked_reasons,
    }


def _effective_mode(
    record: RolloutSurfaceRecord,
    *,
    args: Any | None,
    config: Mapping[str, Any],
    top_level_disabled: bool,
) -> dict[str, Any]:
    top_source = _top_level_source(args)
    if top_level_disabled and record.family in {
        "process",
        "read",
        "write",
        "scheduler",
        "provider_host",
        "mobile_gateway",
        "recovery",
    }:
        return {
            "mode": "disabled",
            "source": top_source,
            "blocked_reasons": ["top-level daemon escape hatch is active"],
        }
    if record.family == "read":
        return _read_mode(record, config)
    if record.family == "read_diagnostics":
        return _boolean_config_mode(
            record,
            config,
            env_name="SASE_DAEMON_FALLBACK_DIAGNOSTICS",
            config_key="daemon.reads.fallback_diagnostics",
            enabled_mode="shadow",
            disabled_mode="disabled",
        )
    if record.family == "scheduler":
        return _scheduler_mode(record, config)
    if record.family == "provider_host":
        return _provider_host_mode(record, config)
    if record.family == "write":
        return {
            "mode": "direct",
            "source": {"type": "registry", "key": record.surface_id, "value": "direct"},
            "blocked_reasons": [],
        }
    if record.family == "mobile_gateway":
        return {
            "mode": "daemon_authoritative",
            "source": {
                "type": "registry",
                "key": record.surface_id,
                "value": "contract",
            },
            "blocked_reasons": [],
        }
    return {
        "mode": "available",
        "source": {"type": "registry", "key": record.surface_id, "value": "available"},
        "blocked_reasons": [],
    }


def _read_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    force_direct = _env_bool("SASE_DAEMON_FORCE_DIRECT")
    if force_direct is True:
        return _mode("direct", "env", "SASE_DAEMON_FORCE_DIRECT", "1")
    global_env = _env_bool("SASE_DAEMON_READS")
    if global_env is False:
        return _mode("direct", "env", "SASE_DAEMON_READS", "0")
    if global_env is True and record.surface_id == "read.global":
        return _mode("read_through", "env", "SASE_DAEMON_READS", "1")

    reads_enabled = _lookup(config, "daemon.reads.enabled")
    if reads_enabled is False:
        return _mode("direct", "config", "daemon.reads.enabled", reads_enabled)
    if record.surface_id == "read.global":
        return _mode(
            "read_through" if reads_enabled is not False else "direct",
            "config",
            "daemon.reads.enabled",
            reads_enabled,
        )

    group = record.surface_id.removeprefix("read.")
    surface_env_name = _surface_env_name(group)
    surface_env = _env_bool(surface_env_name)
    if surface_env is not None:
        return _mode(
            "read_through" if surface_env else "direct",
            "env",
            surface_env_name,
            os.environ.get(surface_env_name),
        )
    key = f"daemon.reads.surfaces.{group}"
    value = _lookup(config, key)
    return _mode("read_through" if value is True else "direct", "config", key, value)


def _scheduler_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    env_names = {
        "scheduler.launch": (
            "SASE_DAEMON_SCHEDULER_LAUNCH_MODE",
            "SASE_SCHEDULER_LAUNCH_MODE",
        ),
        "scheduler.lifecycle": (
            "SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE",
            "SASE_SCHEDULER_LIFECYCLE_MODE",
        ),
        "scheduler.axe": ("SASE_DAEMON_SCHEDULER_AXE_MODE",),
    }[record.surface_id]
    for env_name in env_names:
        parsed = _parse_mode(os.environ.get(env_name), _SCHEDULER_MODE_ALIASES)
        if parsed is not None:
            return _mode(parsed, "env", env_name, os.environ.get(env_name))
    key = record.config_keys[0] if record.config_keys else "daemon.scheduler"
    parsed = _parse_mode(_lookup(config, key), _SCHEDULER_MODE_ALIASES) or "direct"
    if record.surface_id == "scheduler.axe" and parsed == "shadow":
        parsed = "direct"
    return _mode(parsed, "config", key, _lookup(config, key))


def _provider_host_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if os.environ.get("SASE_DISABLE_PROVIDER_HOST_ROUTING"):
        return _mode("direct", "env", "SASE_DISABLE_PROVIDER_HOST_ROUTING", "1")
    operation = _provider_operation(record)
    specific_env = (
        f"SASE_PROVIDER_HOST_{_operation_key(operation).upper()}_MODE"
        if operation
        else None
    )
    if specific_env:
        parsed = _parse_mode(os.environ.get(specific_env), _PROVIDER_HOST_MODE_ALIASES)
        if parsed is not None:
            return _mode(parsed, "env", specific_env, os.environ.get(specific_env))
    parsed = _parse_mode(
        os.environ.get("SASE_PROVIDER_HOST_MODE"), _PROVIDER_HOST_MODE_ALIASES
    )
    if parsed is not None:
        return _mode(
            parsed,
            "env",
            "SASE_PROVIDER_HOST_MODE",
            os.environ.get("SASE_PROVIDER_HOST_MODE"),
        )
    legacy = _env_bool("SASE_PROVIDER_HOST_QUERIES")
    if legacy is not None and operation in _LOW_RISK_PROVIDER_HOST_MODES:
        return _mode(
            "host_preferred" if legacy else "direct",
            "env",
            "SASE_PROVIDER_HOST_QUERIES",
            os.environ.get("SASE_PROVIDER_HOST_QUERIES"),
        )
    if record.surface_id == "provider_host.global":
        key = "daemon.provider_host.default_mode"
        parsed = (
            _parse_mode(_lookup(config, key), _PROVIDER_HOST_MODE_ALIASES) or "direct"
        )
        return _mode(parsed, "config", key, _lookup(config, key))
    key = record.config_keys[0] if record.config_keys else ""
    parsed = _parse_mode(_lookup(config, key), _PROVIDER_HOST_MODE_ALIASES)
    if parsed is None:
        parsed = _LOW_RISK_PROVIDER_HOST_MODES.get(operation or "", "direct")
    return _mode(parsed, "config", key, _lookup(config, key))


def _boolean_config_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
    *,
    env_name: str,
    config_key: str,
    enabled_mode: str,
    disabled_mode: str,
) -> dict[str, Any]:
    env_value = _env_bool(env_name)
    if env_value is not None:
        return _mode(
            enabled_mode if env_value else disabled_mode,
            "env",
            env_name,
            os.environ.get(env_name),
        )
    value = _lookup(config, config_key)
    return _mode(
        enabled_mode if value is True else disabled_mode,
        "config",
        config_key or record.surface_id,
        value,
    )


def _mode(mode: str, source_type: str, key: str, value: Any) -> dict[str, Any]:
    return {
        "mode": mode,
        "source": {"type": source_type, "key": key, "value": value},
        "blocked_reasons": [],
    }


def _top_level_state(args: Any | None) -> dict[str, Any]:
    return {
        "disabled": daemon_disabled(args),
        "source": _top_level_source(args),
    }


def _top_level_source(args: Any | None) -> dict[str, Any]:
    if bool(getattr(args, "no_daemon", False)):
        return {"type": "arg", "key": "--no-daemon", "value": True}
    env_value = os.environ.get(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV)
    if _env_bool(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV) is True:
        return {
            "type": "env",
            "key": TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "value": env_value,
        }
    return {"type": "default", "key": TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV, "value": False}


def _compatibility_status(inspection: DaemonInspection) -> dict[str, Any]:
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
    health = _mapping(rpc.get("health"))
    compatibility = _mapping(health.get("compatibility"))
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


def _observed_capabilities(inspection: DaemonInspection) -> frozenset[str]:
    rpc = inspection.rpc if isinstance(inspection.rpc, dict) else {}
    health = _mapping(rpc.get("health"))
    details = _mapping(health.get("details"))
    capabilities: set[str] = set()
    _collect_string_list(capabilities, health.get("capabilities"))
    _collect_string_list(capabilities, health.get("declared_capabilities"))
    _collect_string_list(capabilities, details.get("capabilities"))
    capabilities_payload = _mapping(details.get("capability_advertisement"))
    _collect_string_list(capabilities, capabilities_payload.get("capabilities"))
    return frozenset(capabilities)


def _gate_coverage(
    report: Mapping[str, Any] | None,
    *,
    observed_capabilities: frozenset[str],
    compatibility_ok: bool,
) -> GateCoverage:
    contract_snapshots = _reported_set(report, "contract_snapshots")
    if compatibility_ok:
        contract_snapshots = frozenset({*contract_snapshots, "local_daemon.v1"})
    return GateCoverage(
        capabilities=frozenset(
            {*observed_capabilities, *_reported_set(report, "capabilities")}
        ),
        contract_snapshots=contract_snapshots,
        parity_gates=_reported_set(report, "parity_gates"),
        perf_gates=_reported_set(report, "perf_gates"),
        recovery_checks=_reported_set(report, "recovery_checks"),
        docs_links=_reported_set(report, "docs_links"),
    )


def _milestone_payloads(coverage: GateCoverage) -> list[dict[str, Any]]:
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


def _parity_status(
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
    health = _mapping(rpc.get("health"))
    details = _mapping(health.get("details"))
    indexing = _mapping(details.get("indexing"))
    projection = _mapping(details.get("projection_db"))
    state = str(indexing.get("state") or projection.get("state") or "not_reported")
    message = str(indexing.get("message") or projection.get("message") or "")
    return {"status": state, "gates": list(record.parity_gates), "message": message}


def _perf_status(
    record: RolloutSurfaceRecord,
    report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not record.perf_gates:
        return {"status": "not_required", "gates": []}
    if report is None:
        return {"status": "not_reported", "gates": list(record.perf_gates)}
    gate_payloads = []
    for gate in record.perf_gates:
        value = _reported_gate_value(report, gate)
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


def _fallback_command(record: RolloutSurfaceRecord, mode: object) -> str | None:
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


def _mode_needs_daemon(mode: str) -> bool:
    return mode in {
        "read_through",
        "write_through",
        "shadow",
        "daemon_authoritative",
        "host_preferred",
        "host_required",
    }


def _load_json_report(path: str | Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    with Path(path).expanduser().open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, Mapping):
        raise ValueError("benchmark report must be a JSON object")
    return data


def _reported_set(report: Mapping[str, Any] | None, key: str) -> frozenset[str]:
    if report is None:
        return frozenset()
    value = report.get(key)
    if isinstance(value, Mapping):
        return frozenset(
            str(item) for item, status in value.items() if _gate_passed(status)
        )
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return frozenset(str(item) for item in value)
    return frozenset()


def _reported_gate_value(report: Mapping[str, Any], gate: str) -> Any | None:
    for key in ("perf_gates", "gates", "results"):
        value = report.get(key)
        if isinstance(value, Mapping) and gate in value:
            return value[gate]
    if gate in report:
        return report[gate]
    return None


def _gate_passed(value: Any) -> bool:
    if isinstance(value, Mapping):
        status = value.get("status")
        return status in {True, "ok", "passed", "pass"}
    return value in {True, "ok", "passed", "pass"}


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _parse_mode(value: object, aliases: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    return aliases.get(value.strip().lower().replace("-", "_"))


def _lookup(config: Mapping[str, Any], path: str) -> Any:
    current: Any = config
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _collect_string_list(target: set[str], value: Any) -> None:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        target.update(str(item) for item in value if isinstance(item, str))


def _surface_env_name(group: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in group.upper())
    return f"SASE_DAEMON_{token}_READS"


def _provider_operation(record: RolloutSurfaceRecord) -> str | None:
    if not record.surface_id.startswith("provider_host."):
        return None
    if record.surface_id == "provider_host.global":
        return None
    if record.parity_gates:
        return record.parity_gates[0].removeprefix("provider_host.parity.")
    return record.surface_id.removeprefix("provider_host.").replace("_", ".")


def _operation_key(operation: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in operation.lower())


def _missing_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    count = 0
    for missing in value.values():
        if isinstance(missing, list):
            count += len(missing)
    return count


def _source_label(source: Mapping[str, Any]) -> str:
    source_type = source.get("type", "unknown")
    key = source.get("key")
    value = source.get("value")
    if key is None:
        return str(source_type)
    return f"{source_type}:{key}={value}"


__all__ = [
    "print_rollout_diagnostics",
    "rollout_diagnostics_payload",
]
