"""Side-effect-free host collection for the portable AXE status snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, tzinfo
from typing import cast

from sase.ace.patch import count_hook_and_agent_runners_global
from sase.ace.hooks.processes import is_process_running

from .config import AxeConfig, load_axe_config
from .desired_state import read_desired_state
from .lifecycle_journal import read_recent_lifecycle_events
from .maintenance import read_maintenance
from .state import (
    LumberjackStatus,
    list_lumberjack_names,
    read_lumberjack_pid,
    read_lumberjack_status,
)
from .status_models import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeLifecycleEvent,
    AxeLifecycleEventKind,
    AxeLumberjackObservation,
    AxeLumberjackReportedState,
    AxeMaintenanceRecord,
    AxeOrchestratorObservation,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusRequest,
    AxeStatusSnapshot,
    classify_axe_status,
)
from ._process_probe import probe_orchestrator
from ._process_types import AxeOrchestratorProbe


Clock = Callable[[], datetime]
_MAX_WIRE_U32 = 2**32 - 1


def collect_axe_status_snapshot(
    *,
    clock: Clock | None = None,
) -> AxeStatusSnapshot:
    """Collect and classify one deterministic, read-only AXE host snapshot."""
    now = (clock or _default_clock)()
    _require_aware_datetime(now)
    generated_at = now.isoformat()

    try:
        config = load_axe_config()
        _validate_config(config)
    except Exception as exc:  # noqa: BLE001 - converted required host input.
        _raise_programming_or_binding_error(exc)
        return _classify_collection_error(
            generated_at=generated_at,
            code="config_read_failed",
            message=_error_message("Unable to load AXE configuration", exc),
        )

    try:
        probe = probe_orchestrator(cleanup=False)
        orchestrator = _collect_orchestrator_observation(probe)
    except Exception as exc:  # noqa: BLE001 - converted required host input.
        _raise_programming_or_binding_error(exc)
        return _classify_collection_error(
            generated_at=generated_at,
            code="orchestrator_probe_failed",
            message=_error_message("Unable to probe the AXE orchestrator", exc),
            config=config,
        )

    try:
        hook_count, agent_count = count_hook_and_agent_runners_global()
        _require_wire_count(hook_count, "hook runner count")
        _require_wire_count(agent_count, "agent runner count")
    except Exception as exc:  # noqa: BLE001 - converted required host input.
        _raise_programming_or_binding_error(exc)
        return _classify_collection_error(
            generated_at=generated_at,
            code="runner_count_failed",
            message=_error_message("Unable to count active AXE runners", exc),
            config=config,
            orchestrator=orchestrator,
        )

    try:
        lumberjacks = _collect_lumberjacks(config, now=now)
    except Exception as exc:  # noqa: BLE001 - converted required host input.
        _raise_programming_or_binding_error(exc)
        return _classify_collection_error(
            generated_at=generated_at,
            code="lumberjack_probe_failed",
            message=_error_message("Unable to probe AXE lumberjacks", exc),
            config=config,
            orchestrator=orchestrator,
            hook_count=hook_count,
            agent_count=agent_count,
        )

    request = AxeStatusRequest(
        schema_version=AXE_STATUS_WIRE_SCHEMA_VERSION,
        generated_at=generated_at,
        desired_state=_collect_desired_state(),
        orchestrator=orchestrator,
        maintenance=_collect_maintenance(now=now),
        hook_runners=AxeRunnerOccupancy(
            current=hook_count,
            maximum=config.max_hook_runners,
        ),
        agent_runners=AxeRunnerOccupancy(
            current=agent_count,
            maximum=config.max_agent_runners,
        ),
        lumberjacks=lumberjacks,
        latest_lifecycle_event=_collect_latest_lifecycle_event(now=now),
        collection_error=None,
    )
    return classify_axe_status(request)


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _require_aware_datetime(value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError("AXE status clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AXE status clock must return a timezone-aware datetime")


def _validate_config(config: AxeConfig) -> None:
    _require_wire_count(config.max_hook_runners, "maximum hook runners")
    _require_wire_count(config.max_agent_runners, "maximum agent runners")
    if not isinstance(config.lumberjacks, dict):
        raise ValueError("AXE lumberjacks configuration must be a mapping")
    for name, lumberjack in config.lumberjacks.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("AXE lumberjack names must be non-empty strings")
        if (
            not isinstance(lumberjack.interval, int)
            or isinstance(lumberjack.interval, bool)
            or not 0 < lumberjack.interval <= _MAX_WIRE_U32
        ):
            raise ValueError(f"AXE lumberjack {name!r} must have a positive interval")
        if not isinstance(lumberjack.chop_names, list) or any(
            not isinstance(chop, str) or not chop.strip()
            for chop in lumberjack.chop_names
        ):
            raise ValueError(f"AXE lumberjack {name!r} has invalid enabled chop names")


def _require_wire_count(value: object, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= _MAX_WIRE_U32
    ):
        raise ValueError(f"{label} must be a non-negative 32-bit integer")


def _collect_orchestrator_observation(
    probe: AxeOrchestratorProbe,
) -> AxeOrchestratorObservation:
    return AxeOrchestratorObservation(
        lifecycle_lock_held=probe.lock_held,
        lock_holder=_process_observation(probe.lock_holder_pid),
        orchestrator_pid_file=_process_observation(probe.orchestrator_pid_file_pid),
        legacy_pid_file=_process_observation(probe.legacy_pid),
    )


def _process_observation(pid: int | None) -> AxeProcessObservation:
    if pid is None:
        return AxeProcessObservation(pid=None, live=None)
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not 0 < pid <= _MAX_WIRE_U32
    ):
        raise ValueError(f"invalid AXE process PID observation: {pid!r}")
    return AxeProcessObservation(pid=pid, live=bool(is_process_running(pid)))


def _collect_desired_state() -> AxeDesiredStateRecord | None:
    try:
        desired = read_desired_state()
    except OSError:
        return None
    if desired is None:
        return None
    return AxeDesiredStateRecord(
        state=desired.state,
        source=desired.source,
        timestamp=desired.timestamp,
    )


def _collect_maintenance(*, now: datetime) -> AxeMaintenanceRecord | None:
    try:
        maintenance = read_maintenance()
    except OSError:
        return None
    if maintenance is None:
        return None
    reason = maintenance.get("reason")
    owner_pid = maintenance.get("pid")
    started_at = maintenance.get("started_at")
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(owner_pid, int)
        or isinstance(owner_pid, bool)
        or not 0 < owner_pid <= _MAX_WIRE_U32
        or not isinstance(started_at, str)
    ):
        return None
    age = _age_seconds(started_at, now=now)
    if age is None:
        return None
    return AxeMaintenanceRecord(
        reason=reason,
        owner_pid=owner_pid,
        started_at=started_at,
        age_seconds=age,
    )


def _collect_latest_lifecycle_event(*, now: datetime) -> AxeLifecycleEvent | None:
    try:
        events = read_recent_lifecycle_events(limit=1)
    except OSError:
        return None
    if not events:
        return None
    event = events[-1]
    event_kind = event.get("event")
    timestamp = event.get("timestamp")
    source = event.get("source")
    outcome = event.get("outcome")
    success = event.get("succeeded")
    reason = event.get("reason")
    orchestrator_pid = event.get("orchestrator_pid")
    if (
        event_kind not in {"start", "stop", "restart"}
        or not isinstance(timestamp, str)
        or not timestamp
        or not isinstance(source, str)
        or not source
        or not isinstance(outcome, str)
        or not outcome
        or not isinstance(success, bool)
        or (reason is not None and (not isinstance(reason, str) or not reason))
        or (
            orchestrator_pid is not None
            and (
                not isinstance(orchestrator_pid, int)
                or isinstance(orchestrator_pid, bool)
                or not 0 < orchestrator_pid <= _MAX_WIRE_U32
            )
        )
    ):
        return None
    return AxeLifecycleEvent(
        event=cast(AxeLifecycleEventKind, event_kind),
        timestamp=timestamp,
        source=source,
        outcome=outcome,
        success=success,
        reason=reason,
        orchestrator_pid=orchestrator_pid,
        age_seconds=_age_seconds(timestamp, now=now),
    )


def _collect_lumberjacks(
    config: AxeConfig,
    *,
    now: datetime,
) -> tuple[AxeLumberjackObservation, ...]:
    configured_names = set(config.lumberjacks)
    state_names = set(_list_state_lumberjack_names())
    observations: list[AxeLumberjackObservation] = []

    for name in sorted(configured_names | state_names):
        configured = name in configured_names
        status = _read_lumberjack_status(name)
        if status is not None and not _valid_lumberjack_status(status, name=name):
            status = None

        pid = status.pid if status is not None else _read_lumberjack_pid(name)
        if pid is not None and not _valid_pid(pid):
            pid = None
        process_live = bool(is_process_running(pid)) if pid is not None else None
        if not configured and process_live is not True:
            continue

        lumberjack_config = config.lumberjacks.get(name)
        interval = lumberjack_config.interval if lumberjack_config is not None else None
        chops = (
            tuple(sorted(set(lumberjack_config.chop_names)))
            if lumberjack_config is not None
            else ()
        )
        observations.append(
            AxeLumberjackObservation(
                name=name,
                configured=configured,
                interval_seconds=interval,
                configured_chops=chops,
                recorded_pid=pid,
                reported_state=(
                    cast(AxeLumberjackReportedState, status.status)
                    if status is not None
                    else None
                ),
                process_live=process_live,
                started_at=status.started_at if status is not None else None,
                start_age_seconds=(
                    _age_seconds(status.started_at, now=now)
                    if status is not None
                    else None
                ),
                heartbeat_at=status.last_cycle if status is not None else None,
                heartbeat_age_seconds=(
                    _age_seconds(status.last_cycle, now=now)
                    if status is not None and status.last_cycle is not None
                    else None
                ),
                cycles_run=status.cycles_run if status is not None else 0,
                errors_encountered=(
                    status.errors_encountered if status is not None else 0
                ),
                uptime_seconds=status.uptime_seconds if status is not None else 0,
            )
        )
    return tuple(observations)


def _list_state_lumberjack_names() -> tuple[str, ...]:
    try:
        return tuple(
            name
            for name in list_lumberjack_names()
            if isinstance(name, str) and bool(name)
        )
    except OSError:
        return ()


def _read_lumberjack_status(name: str) -> LumberjackStatus | None:
    try:
        return read_lumberjack_status(name)
    except OSError:
        return None


def _read_lumberjack_pid(name: str) -> int | None:
    try:
        return read_lumberjack_pid(name)
    except OSError:
        return None


def _valid_lumberjack_status(status: LumberjackStatus, *, name: str) -> bool:
    started_at = getattr(status, "started_at", None)
    if (
        getattr(status, "name", None) != name
        or not _valid_pid(getattr(status, "pid", None))
        or getattr(status, "status", None) not in {"running", "stopped", "error"}
        or not isinstance(getattr(status, "interval", None), int)
        or isinstance(getattr(status, "interval", None), bool)
        or getattr(status, "interval", 0) <= 0
        or not isinstance(started_at, str)
        or _parse_timestamp(started_at, default_timezone=UTC) is None
    ):
        return False
    last_cycle = getattr(status, "last_cycle", None)
    if last_cycle is not None and (
        not isinstance(last_cycle, str)
        or _parse_timestamp(last_cycle, default_timezone=UTC) is None
    ):
        return False
    chops = getattr(status, "chops", None)
    if not isinstance(chops, list) or any(
        not isinstance(chop, str) or not chop for chop in chops
    ):
        return False
    return all(
        isinstance(getattr(status, field, None), int)
        and not isinstance(getattr(status, field, None), bool)
        and getattr(status, field) >= 0
        for field in ("cycles_run", "errors_encountered", "uptime_seconds")
    )


def _valid_pid(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= _MAX_WIRE_U32
    )


def _age_seconds(value: object, *, now: datetime) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    timestamp = _parse_timestamp(value, default_timezone=now.tzinfo)
    if timestamp is None:
        return None
    return int(max(0.0, (now - timestamp.astimezone(now.tzinfo)).total_seconds()))


def _parse_timestamp(
    value: str,
    *,
    default_timezone: tzinfo | None,
) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        if default_timezone is None:
            return None
        timestamp = timestamp.replace(tzinfo=default_timezone)
    if timestamp.utcoffset() is None:
        return None
    return timestamp


def _classify_collection_error(
    *,
    generated_at: str,
    code: str,
    message: str,
    config: AxeConfig | None = None,
    orchestrator: AxeOrchestratorObservation | None = None,
    hook_count: int = 0,
    agent_count: int = 0,
) -> AxeStatusSnapshot:
    request = AxeStatusRequest(
        schema_version=AXE_STATUS_WIRE_SCHEMA_VERSION,
        generated_at=generated_at,
        desired_state=None,
        orchestrator=orchestrator or _empty_orchestrator_observation(),
        maintenance=None,
        hook_runners=AxeRunnerOccupancy(
            current=hook_count,
            maximum=config.max_hook_runners if config is not None else 0,
        ),
        agent_runners=AxeRunnerOccupancy(
            current=agent_count,
            maximum=config.max_agent_runners if config is not None else 0,
        ),
        lumberjacks=(),
        latest_lifecycle_event=None,
        collection_error=AxeStatusCollectionError(code=code, message=message),
    )
    return classify_axe_status(request)


def _empty_orchestrator_observation() -> AxeOrchestratorObservation:
    missing = AxeProcessObservation(pid=None, live=None)
    return AxeOrchestratorObservation(
        lifecycle_lock_held=False,
        lock_holder=missing,
        orchestrator_pid_file=missing,
        legacy_pid_file=missing,
    )


def _raise_programming_or_binding_error(exc: Exception) -> None:
    if isinstance(
        exc,
        (AssertionError, AttributeError, ImportError, NameError, TypeError),
    ):
        raise exc


def _error_message(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{prefix}: {detail}" if detail else prefix


collect_axe_status = collect_axe_status_snapshot


__all__ = [
    "Clock",
    "collect_axe_status",
    "collect_axe_status_snapshot",
]
