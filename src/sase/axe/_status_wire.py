"""Strict rehydration for the portable AXE status wire contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from ._status_records import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeDesiredStateValue,
    AxeLifecycleEvent,
    AxeLifecycleEventKind,
    AxeLumberjackReportedState,
    AxeLumberjackState,
    AxeLumberjackStatus,
    AxeMaintenanceRecord,
    AxeOrchestratorCoherence,
    AxeOrchestratorState,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusHealth,
    AxeStatusIssue,
    AxeStatusIssueSeverity,
    AxeStatusSnapshot,
    AxeStatusState,
)


class AxeStatusWireError(ValueError):
    """The Rust binding returned a malformed or incompatible status payload."""


def rehydrate_axe_status_snapshot(payload: object) -> AxeStatusSnapshot:
    """Strictly rehydrate one Rust response into frozen Python records."""
    root = _record(
        payload,
        "$",
        {
            "schema_version",
            "generated_at",
            "state",
            "health",
            "summary",
            "exit_code",
            "desired_state",
            "orchestrator",
            "maintenance",
            "hook_runners",
            "agent_runners",
            "lumberjacks",
            "latest_lifecycle_event",
            "issues",
            "collection_error",
        },
    )
    schema_version = _integer(root["schema_version"], "$.schema_version")
    if schema_version != AXE_STATUS_WIRE_SCHEMA_VERSION:
        raise AxeStatusWireError(
            "AXE status response schema mismatch: "
            f"got {schema_version}, expected {AXE_STATUS_WIRE_SCHEMA_VERSION}"
        )

    return AxeStatusSnapshot(
        schema_version=schema_version,
        generated_at=_string(root["generated_at"], "$.generated_at"),
        state=cast(
            AxeStatusState,
            _literal(
                root["state"],
                "$.state",
                {
                    "running",
                    "maintenance",
                    "stopped",
                    "not_started",
                    "down",
                    "degraded",
                    "error",
                },
            ),
        ),
        health=cast(
            AxeStatusHealth,
            _literal(
                root["health"],
                "$.health",
                {"healthy", "unhealthy", "error"},
            ),
        ),
        summary=_string(root["summary"], "$.summary"),
        exit_code=_integer(root["exit_code"], "$.exit_code"),
        desired_state=_optional_desired_state(root["desired_state"], "$.desired_state"),
        orchestrator=_orchestrator_status(root["orchestrator"], "$.orchestrator"),
        maintenance=_optional_maintenance(root["maintenance"], "$.maintenance"),
        hook_runners=_runner_occupancy(root["hook_runners"], "$.hook_runners"),
        agent_runners=_runner_occupancy(root["agent_runners"], "$.agent_runners"),
        lumberjacks=tuple(
            _lumberjack_status(item, f"$.lumberjacks[{index}]")
            for index, item in enumerate(_list(root["lumberjacks"], "$.lumberjacks"))
        ),
        latest_lifecycle_event=_optional_lifecycle_event(
            root["latest_lifecycle_event"], "$.latest_lifecycle_event"
        ),
        issues=tuple(
            _status_issue(item, f"$.issues[{index}]")
            for index, item in enumerate(_list(root["issues"], "$.issues"))
        ),
        collection_error=_optional_collection_error(
            root["collection_error"], "$.collection_error"
        ),
    )


def _process_observation(value: object, path: str) -> AxeProcessObservation:
    record = _record(value, path, {"pid", "live"})
    pid = _optional_positive_integer(record["pid"], f"{path}.pid")
    live = _optional_boolean(record["live"], f"{path}.live")
    if (pid is None) != (live is None):
        raise AxeStatusWireError(f"{path}: pid and live must both be null or present")
    return AxeProcessObservation(pid=pid, live=live)


def _desired_state(value: object, path: str) -> AxeDesiredStateRecord:
    record = _record(value, path, {"state", "source", "timestamp"})
    return AxeDesiredStateRecord(
        state=cast(
            AxeDesiredStateValue,
            _literal(record["state"], f"{path}.state", {"running", "stopped"}),
        ),
        source=_string(record["source"], f"{path}.source"),
        timestamp=_string(record["timestamp"], f"{path}.timestamp"),
    )


def _optional_desired_state(value: object, path: str) -> AxeDesiredStateRecord | None:
    return None if value is None else _desired_state(value, path)


def _maintenance(value: object, path: str) -> AxeMaintenanceRecord:
    record = _record(value, path, {"reason", "owner_pid", "started_at", "age_seconds"})
    return AxeMaintenanceRecord(
        reason=_string(record["reason"], f"{path}.reason"),
        owner_pid=_positive_integer(record["owner_pid"], f"{path}.owner_pid"),
        started_at=_string(record["started_at"], f"{path}.started_at"),
        age_seconds=_integer(record["age_seconds"], f"{path}.age_seconds"),
    )


def _optional_maintenance(value: object, path: str) -> AxeMaintenanceRecord | None:
    return None if value is None else _maintenance(value, path)


def _runner_occupancy(value: object, path: str) -> AxeRunnerOccupancy:
    record = _record(value, path, {"current", "maximum"})
    return AxeRunnerOccupancy(
        current=_integer(record["current"], f"{path}.current"),
        maximum=_integer(record["maximum"], f"{path}.maximum"),
    )


def _lifecycle_event(value: object, path: str) -> AxeLifecycleEvent:
    record = _record(
        value,
        path,
        {
            "event",
            "timestamp",
            "source",
            "outcome",
            "success",
            "reason",
            "orchestrator_pid",
            "age_seconds",
        },
    )
    return AxeLifecycleEvent(
        event=cast(
            AxeLifecycleEventKind,
            _literal(record["event"], f"{path}.event", {"start", "stop", "restart"}),
        ),
        timestamp=_string(record["timestamp"], f"{path}.timestamp"),
        source=_string(record["source"], f"{path}.source"),
        outcome=_string(record["outcome"], f"{path}.outcome"),
        success=_boolean(record["success"], f"{path}.success"),
        reason=_optional_string(record["reason"], f"{path}.reason"),
        orchestrator_pid=_optional_positive_integer(
            record["orchestrator_pid"], f"{path}.orchestrator_pid"
        ),
        age_seconds=_optional_integer(record["age_seconds"], f"{path}.age_seconds"),
    )


def _optional_lifecycle_event(value: object, path: str) -> AxeLifecycleEvent | None:
    return None if value is None else _lifecycle_event(value, path)


def _collection_error(value: object, path: str) -> AxeStatusCollectionError:
    record = _record(value, path, {"code", "message"})
    return AxeStatusCollectionError(
        code=_string(record["code"], f"{path}.code"),
        message=_string(record["message"], f"{path}.message"),
    )


def _optional_collection_error(
    value: object, path: str
) -> AxeStatusCollectionError | None:
    return None if value is None else _collection_error(value, path)


def _orchestrator_status(value: object, path: str) -> AxeOrchestratorStatus:
    record = _record(
        value,
        path,
        {
            "state",
            "coherence",
            "live_pids",
            "lifecycle_lock_held",
            "lock_holder",
            "orchestrator_pid_file",
            "legacy_pid_file",
        },
    )
    return AxeOrchestratorStatus(
        state=cast(
            AxeOrchestratorState,
            _literal(
                record["state"],
                f"{path}.state",
                {"running", "stopped", "incoherent"},
            ),
        ),
        coherence=cast(
            AxeOrchestratorCoherence,
            _literal(
                record["coherence"],
                f"{path}.coherence",
                {"coherent", "incoherent"},
            ),
        ),
        live_pids=tuple(
            _positive_integer(item, f"{path}.live_pids[{index}]")
            for index, item in enumerate(
                _list(record["live_pids"], f"{path}.live_pids")
            )
        ),
        lifecycle_lock_held=_boolean(
            record["lifecycle_lock_held"], f"{path}.lifecycle_lock_held"
        ),
        lock_holder=_process_observation(record["lock_holder"], f"{path}.lock_holder"),
        orchestrator_pid_file=_process_observation(
            record["orchestrator_pid_file"], f"{path}.orchestrator_pid_file"
        ),
        legacy_pid_file=_process_observation(
            record["legacy_pid_file"], f"{path}.legacy_pid_file"
        ),
    )


def _lumberjack_status(value: object, path: str) -> AxeLumberjackStatus:
    record = _record(
        value,
        path,
        {
            "name",
            "state",
            "stale_threshold_seconds",
            "configured",
            "interval_seconds",
            "configured_chops",
            "recorded_pid",
            "reported_state",
            "process_live",
            "started_at",
            "start_age_seconds",
            "heartbeat_at",
            "heartbeat_age_seconds",
            "cycles_run",
            "errors_encountered",
            "uptime_seconds",
        },
    )
    row = AxeLumberjackStatus(
        name=_string(record["name"], f"{path}.name"),
        state=cast(
            AxeLumberjackState,
            _literal(
                record["state"],
                f"{path}.state",
                {
                    "running",
                    "not_reporting",
                    "stale_process",
                    "stale_heartbeat",
                    "error",
                    "orphaned",
                },
            ),
        ),
        stale_threshold_seconds=_optional_integer(
            record["stale_threshold_seconds"],
            f"{path}.stale_threshold_seconds",
        ),
        configured=_boolean(record["configured"], f"{path}.configured"),
        interval_seconds=_optional_integer(
            record["interval_seconds"], f"{path}.interval_seconds"
        ),
        configured_chops=tuple(
            _string(item, f"{path}.configured_chops[{index}]")
            for index, item in enumerate(
                _list(record["configured_chops"], f"{path}.configured_chops")
            )
        ),
        recorded_pid=_optional_positive_integer(
            record["recorded_pid"], f"{path}.recorded_pid"
        ),
        reported_state=cast(
            AxeLumberjackReportedState | None,
            _optional_literal(
                record["reported_state"],
                f"{path}.reported_state",
                {"running", "stopped", "error"},
            ),
        ),
        process_live=_optional_boolean(record["process_live"], f"{path}.process_live"),
        started_at=_optional_string(record["started_at"], f"{path}.started_at"),
        start_age_seconds=_optional_integer(
            record["start_age_seconds"], f"{path}.start_age_seconds"
        ),
        heartbeat_at=_optional_string(record["heartbeat_at"], f"{path}.heartbeat_at"),
        heartbeat_age_seconds=_optional_integer(
            record["heartbeat_age_seconds"],
            f"{path}.heartbeat_age_seconds",
        ),
        cycles_run=_integer(record["cycles_run"], f"{path}.cycles_run"),
        errors_encountered=_integer(
            record["errors_encountered"], f"{path}.errors_encountered"
        ),
        uptime_seconds=_integer(record["uptime_seconds"], f"{path}.uptime_seconds"),
    )
    if (row.recorded_pid is None) != (row.process_live is None):
        raise AxeStatusWireError(
            f"{path}: recorded_pid and process_live must both be null or present"
        )
    if (row.started_at is None) != (row.start_age_seconds is None):
        raise AxeStatusWireError(
            f"{path}: started_at and start_age_seconds must both be null or present"
        )
    if (row.heartbeat_at is None) != (row.heartbeat_age_seconds is None):
        raise AxeStatusWireError(
            f"{path}: heartbeat_at and heartbeat_age_seconds must both be null "
            "or present"
        )
    if row.reported_state is not None and row.recorded_pid is None:
        raise AxeStatusWireError(f"{path}: reported_state requires recorded_pid")
    return row


def _status_issue(value: object, path: str) -> AxeStatusIssue:
    record = _record(
        value,
        path,
        {"code", "severity", "subject", "summary", "suggested_command"},
    )
    return AxeStatusIssue(
        code=_string(record["code"], f"{path}.code"),
        severity=cast(
            AxeStatusIssueSeverity,
            _literal(record["severity"], f"{path}.severity", {"warning", "error"}),
        ),
        subject=_optional_string(record["subject"], f"{path}.subject"),
        summary=_string(record["summary"], f"{path}.summary"),
        suggested_command=_optional_string(
            record["suggested_command"], f"{path}.suggested_command"
        ),
    )


def _record(
    value: object,
    path: str,
    fields: set[str],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AxeStatusWireError(f"{path}: expected an object")
    string_keys = {key for key in value if isinstance(key, str)}
    if len(string_keys) != len(value):
        raise AxeStatusWireError(f"{path}: object keys must be strings")
    missing = sorted(fields - string_keys)
    extra = sorted(string_keys - fields)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing fields {missing}")
        if extra:
            parts.append(f"unknown fields {extra}")
        raise AxeStatusWireError(f"{path}: {', '.join(parts)}")
    return cast(Mapping[str, object], value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise AxeStatusWireError(f"{path}: expected a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise AxeStatusWireError(f"{path}: expected a string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    return None if value is None else _string(value, path)


def _integer(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AxeStatusWireError(f"{path}: expected a non-negative integer")
    return value


def _optional_integer(value: object, path: str) -> int | None:
    return None if value is None else _integer(value, path)


def _positive_integer(value: object, path: str) -> int:
    integer = _integer(value, path)
    if integer == 0:
        raise AxeStatusWireError(f"{path}: expected a positive integer")
    return integer


def _optional_positive_integer(value: object, path: str) -> int | None:
    return None if value is None else _positive_integer(value, path)


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise AxeStatusWireError(f"{path}: expected a boolean")
    return value


def _optional_boolean(value: object, path: str) -> bool | None:
    return None if value is None else _boolean(value, path)


def _literal(value: object, path: str, allowed: set[str]) -> str:
    string = _string(value, path)
    if string not in allowed:
        raise AxeStatusWireError(
            f"{path}: expected one of {sorted(allowed)}, got {string!r}"
        )
    return string


def _optional_literal(
    value: object,
    path: str,
    allowed: set[str],
) -> str | None:
    return None if value is None else _literal(value, path, allowed)
