"""Shared helpers for daemon rollout diagnostics."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sase.daemon.rollout_registry import RolloutSurfaceRecord

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def mode_needs_daemon(mode: str) -> bool:
    return mode in {
        "read_through",
        "write_through",
        "shadow",
        "daemon_authoritative",
        "host_preferred",
        "host_required",
    }


def load_json_report(path: str | Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    with Path(path).expanduser().open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, Mapping):
        raise ValueError("benchmark report must be a JSON object")
    return data


def reported_set(report: Mapping[str, Any] | None, key: str) -> frozenset[str]:
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


def reported_gate_value(report: Mapping[str, Any], gate: str) -> Any | None:
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


def env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def parse_mode(value: object, aliases: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    return aliases.get(value.strip().lower().replace("-", "_"))


def lookup(config: Mapping[str, Any], path: str) -> Any:
    current: Any = config
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def collect_string_list(target: set[str], value: Any) -> None:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        target.update(str(item) for item in value if isinstance(item, str))


def surface_env_name(group: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in group.upper())
    return f"SASE_DAEMON_{token}_READS"


def provider_operation(record: RolloutSurfaceRecord) -> str | None:
    if not record.surface_id.startswith("provider_host."):
        return None
    if record.surface_id == "provider_host.global":
        return None
    if record.parity_gates:
        return record.parity_gates[0].removeprefix("provider_host.parity.")
    return record.surface_id.removeprefix("provider_host.").replace("_", ".")


def operation_key(operation: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in operation.lower())


def missing_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    count = 0
    for missing in value.values():
        if isinstance(missing, list):
            count += len(missing)
    return count


def source_label(source: Mapping[str, Any]) -> str:
    source_type = source.get("type", "unknown")
    key = source.get("key")
    value = source.get("value")
    if key is None:
        return str(source_type)
    return f"{source_type}:{key}={value}"


__all__ = [
    "collect_string_list",
    "env_bool",
    "_gate_passed",
    "load_json_report",
    "lookup",
    "mapping",
    "missing_count",
    "mode_needs_daemon",
    "operation_key",
    "parse_mode",
    "provider_operation",
    "reported_gate_value",
    "reported_set",
    "source_label",
    "surface_env_name",
]
