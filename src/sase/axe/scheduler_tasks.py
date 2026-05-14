"""Daemon scheduler task helpers for axe work.

The daemon queue stores axe jobs as typed scheduler tasks, while Python remains
the host that executes chops, lumberjack ticks, and related side effects.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from sase.daemon.client import LocalDaemonClient
from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION
from sase.daemon.errors import LocalDaemonError
from sase.daemon.scheduler import (
    SchedulerAxeTaskSpec,
    SchedulerAxeTaskSubmit,
    submit_scheduler_axe_tasks,
)
from sase.daemon.scheduler_config import scheduler_axe_disable_reason

from .chop_runner import (
    ONESHOT_LUMBERJACK_NAME,
    AmbiguousChopError,
    ChopNotFoundError,
    ChopRunOutcome,
    find_configured_chop,
    run_configured_chop_once,
)
from .chop_script_runner import discover_chop_script
from .config import AxeConfig, ChopConfig, load_axe_config
from .state import ChopRunSource


class _AxeSchedulerTaskError(RuntimeError):
    """Raised when an axe scheduler task cannot be prepared or executed."""


@dataclass(frozen=True)
class _AxeSchedulerSubmitOutcome:
    submitted: bool
    response: dict[str, Any] | None = None
    fallback_reason: str | None = None
    fallback_message: str | None = None


def _project_id_for_cwd(cwd: str | None = None) -> str:
    return os.path.abspath(cwd or os.getcwd())


def _chop_task_spec(
    *,
    project_id: str,
    chop_name: str,
    lumberjack_name: str | None,
    source: str,
    started_by: str | None,
) -> SchedulerAxeTaskSpec:
    task_key = f"{lumberjack_name or '*'}:{chop_name}"
    return SchedulerAxeTaskSpec(
        project_id=project_id,
        task_kind="chop",
        task_key=task_key,
        metadata={
            "chop_name": chop_name,
            "lumberjack_name": lumberjack_name,
            "source": source,
            "started_by": started_by,
        },
    )


def scheduler_submit_for_chop(
    *,
    chop_name: str,
    lumberjack_name: str | None = None,
    source: str = "oneshot",
    started_by: str | None = "cli",
    dedupe_key: str | None = None,
    client: LocalDaemonClient | None = None,
) -> _AxeSchedulerSubmitOutcome:
    """Submit one chop task to the daemon scheduler when axe mode allows it."""

    disable = scheduler_axe_disable_reason()
    if disable is not None:
        return _AxeSchedulerSubmitOutcome(
            submitted=False,
            fallback_reason=disable.reason,
            fallback_message=disable.message,
        )

    project_id = _project_id_for_cwd()
    if dedupe_key is None:
        dedupe_key = f"manual:{uuid.uuid4().hex}"
    request = SchedulerAxeTaskSubmit(
        project_id=project_id,
        idempotency_key=f"axe:{project_id}:chop:{lumberjack_name or '*'}:{chop_name}:{dedupe_key}",
        tasks=[
            _chop_task_spec(
                project_id=project_id,
                chop_name=chop_name,
                lumberjack_name=lumberjack_name,
                source=source,
                started_by=started_by,
            )
        ],
        metadata={"source": source, "started_by": started_by},
    )
    try:
        response = submit_scheduler_axe_tasks(client or LocalDaemonClient(), request)
    except LocalDaemonError as exc:
        return _AxeSchedulerSubmitOutcome(
            submitted=False,
            fallback_reason=getattr(exc, "fallback_reason", None) or "daemon_error",
            fallback_message=str(exc),
        )
    return _AxeSchedulerSubmitOutcome(submitted=True, response=response)


def prepare_axe_task(request: dict[str, Any]) -> dict[str, Any]:
    task = _axe_task_from_request(request)
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "operation": "prepare-axe-task",
        "status": "prepared",
        "project_id": task["project_id"],
        "batch_id": task["batch_id"],
        "slot_id": task["slot_id"],
        "queue_id": task["queue_id"],
        "task": task["axe_task"],
    }


def execute_axe_task(
    request: dict[str, Any],
    *,
    execute_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    prepared = prepare_axe_task(request)
    runner = execute_fn or _execute_axe_task_payload
    old_value = os.environ.get("SASE_DAEMON_SCHEDULER_AXE_HOST_BRIDGE")
    os.environ["SASE_DAEMON_SCHEDULER_AXE_HOST_BRIDGE"] = "1"
    try:
        result = runner(prepared["task"])
    except Exception as exc:
        return {
            **_base_response(prepared),
            "status": "failed",
            "duration_ms": _elapsed_ms(started),
            "result": None,
            "failure": {
                "type": type(exc).__name__,
                "message": str(exc),
                "retryable": False,
            },
        }
    finally:
        if old_value is None:
            os.environ.pop("SASE_DAEMON_SCHEDULER_AXE_HOST_BRIDGE", None)
        else:
            os.environ["SASE_DAEMON_SCHEDULER_AXE_HOST_BRIDGE"] = old_value

    return {
        **_base_response(prepared),
        "status": "completed",
        "duration_ms": _elapsed_ms(started),
        "result": result,
        "failure": None,
    }


def _execute_axe_task_payload(task: dict[str, Any]) -> dict[str, Any]:
    kind = _required_str(task, "task_kind")
    metadata = _dict_or_empty(task.get("metadata"))
    config = load_axe_config()
    if kind == "chop":
        outcome = _execute_chop_task(metadata, config)
        return _chop_outcome_to_wire(outcome)
    if kind == "lumberjack_tick":
        lumberjack_name = _required_str(metadata, "lumberjack_name")
        if lumberjack_name not in config.lumberjacks:
            raise _AxeSchedulerTaskError(f"unknown lumberjack '{lumberjack_name}'")
        from .lumberjack import Lumberjack

        lumberjack = Lumberjack(
            lumberjack_name,
            config.lumberjacks[lumberjack_name],
            config,
        )
        lumberjack._run_tick()
        return {
            "task_kind": kind,
            "lumberjack_name": lumberjack_name,
            "status": "success",
        }
    raise _AxeSchedulerTaskError(f"unsupported axe task kind '{kind}'")


def _execute_chop_task(
    metadata: dict[str, Any],
    config: AxeConfig,
) -> ChopRunOutcome:
    chop_name = _required_str(metadata, "chop_name")
    lumberjack_override = _optional_str(metadata.get("lumberjack_name"))
    source = _chop_run_source(_optional_str(metadata.get("source")) or "scheduled")
    started_by = _optional_str(metadata.get("started_by"))
    try:
        match = find_configured_chop(config, chop_name, lumberjack_override)
        lumberjack_name = match.lumberjack_name
        chop_cfg = match.chop
        chop_timeout_default = match.lumberjack.chop_timeout
    except AmbiguousChopError:
        raise
    except ChopNotFoundError:
        if lumberjack_override is not None:
            raise
        script = discover_chop_script(chop_name, config.chop_script_dirs)
        if script is None:
            raise
        lumberjack_name = ONESHOT_LUMBERJACK_NAME
        chop_cfg = ChopConfig(name=chop_name, description="")
        chop_timeout_default = None

    return run_configured_chop_once(
        lumberjack_name=lumberjack_name,
        chop=chop_cfg,
        axe_config=config,
        chop_timeout_default=chop_timeout_default,
        source=source,
        started_by=started_by,
    )


def _axe_task_from_request(request: dict[str, Any]) -> dict[str, Any]:
    raw_slot = request.get("slot", request)
    if not isinstance(raw_slot, dict):
        raise _AxeSchedulerTaskError("slot must be an object")
    raw_task_id = raw_slot.get("task_id")
    if not isinstance(raw_task_id, dict):
        raw_task_id = {}
    raw_spec = raw_slot.get("launch_spec", raw_slot.get("launch"))
    if not isinstance(raw_spec, dict):
        raise _AxeSchedulerTaskError("slot.launch_spec must be an object")
    raw_metadata = raw_spec.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise _AxeSchedulerTaskError("slot.launch_spec.metadata must be an object")
    raw_axe_task = raw_metadata.get("axe_task")
    if not isinstance(raw_axe_task, dict):
        raise _AxeSchedulerTaskError("slot metadata must include axe_task")
    if raw_metadata.get("scheduler_task_kind") != "axe":
        raise _AxeSchedulerTaskError("slot is not an axe scheduler task")

    return {
        "project_id": _required_str(raw_spec, "project_id"),
        "batch_id": _optional_str(raw_task_id.get("batch_id"))
        or _optional_str(raw_slot.get("batch_id"))
        or "batch",
        "slot_id": _optional_str(raw_task_id.get("slot_id"))
        or _optional_str(raw_slot.get("slot_id"))
        or "slot",
        "queue_id": _optional_str(raw_task_id.get("queue_id"))
        or _optional_str(raw_slot.get("queue_id"))
        or "axe",
        "axe_task": raw_axe_task,
    }


def _base_response(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "operation": "execute-axe-task",
        "project_id": prepared["project_id"],
        "batch_id": prepared["batch_id"],
        "slot_id": prepared["slot_id"],
        "queue_id": prepared["queue_id"],
    }


def _chop_outcome_to_wire(outcome: ChopRunOutcome) -> dict[str, Any]:
    return {
        "task_kind": "chop",
        "lumberjack_name": outcome.lumberjack_name,
        "chop_name": outcome.chop_name,
        "status": outcome.status,
        "run_id": outcome.run_id,
        "exit_code": outcome.exit_code,
        "agent_pid": outcome.agent_pid,
        "output_bytes": outcome.output_bytes,
        "error": str(outcome.error) if outcome.error is not None else None,
        "traceback": outcome.traceback,
    }


def _required_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise _AxeSchedulerTaskError(f"{key} must be a non-empty string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _chop_run_source(value: str) -> ChopRunSource:
    if value in {"scheduled", "manual", "oneshot"}:
        return cast(ChopRunSource, value)
    return "scheduled"
