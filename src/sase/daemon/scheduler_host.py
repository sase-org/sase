"""Python host bridge for daemon scheduler launch slots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from sase.agent.launch_types import AgentLaunchResult
from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION

LaunchFn = Callable[[str], list[AgentLaunchResult]]


class SchedulerHostBridgeError(RuntimeError):
    """Raised when a scheduler host bridge request cannot be fulfilled."""


@dataclass(frozen=True)
class SchedulerHostLaunchSpec:
    project_id: str
    prompt: str
    cwd: str | None = None
    model: str | None = None
    parent_agent_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchedulerHostSlot:
    project_id: str
    batch_id: str
    slot_id: str
    queue_id: str
    slot_index: int
    launch_spec: SchedulerHostLaunchSpec
    status: str | None = None


def prepare_launch_slot(request: dict[str, Any]) -> dict[str, Any]:
    """Validate one scheduler slot and return the exact host launch input."""
    slot = scheduler_host_slot_from_request(request)
    prompt = _prompt_for_launch_spec(slot.launch_spec)
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "operation": "prepare-launch-slot",
        "status": "prepared",
        "project_id": slot.project_id,
        "batch_id": slot.batch_id,
        "slot_id": slot.slot_id,
        "queue_id": slot.queue_id,
        "slot_index": slot.slot_index,
        "launch": {
            "prompt": prompt,
            "cwd": slot.launch_spec.cwd,
            "model": slot.launch_spec.model,
            "parent_agent_id": slot.launch_spec.parent_agent_id,
            "workflow_id": slot.launch_spec.workflow_id,
            "metadata": slot.launch_spec.metadata,
            "agent_name": planned_name_for_prompt(prompt),
        },
    }


def execute_launch_slot(
    request: dict[str, Any],
    *,
    launch_fn: LaunchFn | None = None,
) -> dict[str, Any]:
    """Execute one queued scheduler slot through the existing Python launcher."""
    prepared = prepare_launch_slot(request)
    prompt = prepared["launch"]["prompt"]
    cwd = prepared["launch"]["cwd"]
    launcher = launch_fn or _default_launch_fn
    try:
        with _launch_cwd(cwd):
            results = launcher(prompt)
    except Exception as exc:
        return {
            **_base_response(prepared, operation="execute-launch-slot"),
            "status": "failed",
            "primary": None,
            "slots": [],
            "failure": _failure_payload(exc),
        }

    if not results:
        return {
            **_base_response(prepared, operation="execute-launch-slot"),
            "status": "failed",
            "primary": None,
            "slots": [],
            "failure": {
                "type": "empty_launch_result",
                "message": "agent launch produced no results",
                "retryable": False,
            },
        }

    slot_results = [
        _result_to_wire(str(index), result, prepared)
        for index, result in enumerate(results)
    ]
    return {
        **_base_response(prepared, operation="execute-launch-slot"),
        "status": "launched",
        "primary": slot_results[0],
        "slots": slot_results,
        "failure": None,
    }


def cancel_launch_slot(
    request: dict[str, Any],
    *,
    kill_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Cancel or kill the process associated with a launched scheduler slot."""
    slot = scheduler_host_slot_from_request(request)
    name = _cancel_target_name(request, slot)
    if not name:
        raise SchedulerHostBridgeError(
            "cancel-launch-slot requires name or metadata.agent_name"
        )
    killer = kill_fn or _default_kill_fn
    result = killer(name)
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "operation": "cancel-launch-slot",
        "project_id": slot.project_id,
        "batch_id": slot.batch_id,
        "slot_id": slot.slot_id,
        "queue_id": slot.queue_id,
        "name": name,
        "status": getattr(result, "status", None) or "cancelled",
        "pid": getattr(result, "pid", None),
        "changed": bool(getattr(result, "changed", False)),
        "message": str(getattr(result, "message", "")),
    }


def handle_scheduler_host_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one hidden scheduler host bridge operation over JSON stdin/stdout."""
    try:
        request = _read_request(stdin)
        operation = getattr(args, "daemon_scheduler_bridge_subcommand", None)
        if operation == "prepare-launch-slot":
            response = prepare_launch_slot(request)
        elif operation == "execute-launch-slot":
            response = execute_launch_slot(request)
        elif operation == "cancel-launch-slot":
            response = cancel_launch_slot(request)
        else:
            raise SchedulerHostBridgeError("unknown scheduler host bridge operation")
    except (SchedulerHostBridgeError, ValueError, TypeError) as exc:
        print(f"scheduler host bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def scheduler_host_slot_from_request(request: dict[str, Any]) -> SchedulerHostSlot:
    raw_slot = request.get("slot", request)
    if not isinstance(raw_slot, dict):
        raise SchedulerHostBridgeError("slot must be an object")

    raw_task = raw_slot.get("task_id")
    if not isinstance(raw_task, dict):
        raw_task = {}
    raw_spec = raw_slot.get("launch_spec", raw_slot.get("launch"))
    if not isinstance(raw_spec, dict):
        raise SchedulerHostBridgeError("slot.launch_spec must be an object")

    spec = SchedulerHostLaunchSpec(
        project_id=_required_str(raw_spec, "project_id"),
        prompt=_required_str(raw_spec, "prompt"),
        cwd=_optional_str(raw_spec.get("cwd")),
        model=_optional_str(raw_spec.get("model")),
        parent_agent_id=_optional_str(raw_spec.get("parent_agent_id")),
        workflow_id=_optional_str(raw_spec.get("workflow_id")),
        metadata=_dict_or_empty(raw_spec.get("metadata")),
    )
    project_id = _optional_str(raw_slot.get("project_id")) or spec.project_id
    if project_id != spec.project_id:
        raise SchedulerHostBridgeError(
            "slot project_id does not match launch_spec.project_id"
        )
    batch_id = _optional_str(raw_task.get("batch_id")) or _optional_str(
        raw_slot.get("batch_id")
    )
    slot_id = _optional_str(raw_task.get("slot_id")) or _optional_str(
        raw_slot.get("slot_id")
    )
    queue_id = _optional_str(raw_task.get("queue_id")) or _optional_str(
        raw_slot.get("queue_id")
    )
    return SchedulerHostSlot(
        project_id=project_id,
        batch_id=batch_id or "batch",
        slot_id=slot_id or "slot",
        queue_id=queue_id or "agents",
        slot_index=_optional_int(raw_slot.get("slot_index")) or 0,
        status=_optional_str(raw_slot.get("status")),
        launch_spec=spec,
    )


def _prompt_for_launch_spec(spec: SchedulerHostLaunchSpec) -> str:
    prompt = spec.prompt.strip()
    if not prompt:
        raise SchedulerHostBridgeError("launch_spec.prompt must be non-empty")
    if spec.model and not _MODEL_DIRECTIVE_RE.search(prompt):
        prompt = f"%model:{spec.model}\n{prompt}"
    return prompt


def planned_name_for_prompt(prompt: str) -> str | None:
    from sase.agent.multi_prompt_references import extract_static_name_directive

    return extract_static_name_directive(prompt)


def _default_launch_fn(prompt: str) -> list[AgentLaunchResult]:
    from sase.agent.launcher import launch_agents_from_cwd

    return launch_agents_from_cwd(prompt)


def _default_kill_fn(name: str) -> Any:
    from sase.agent.running import kill_named_agent

    return kill_named_agent(name, exact_name=True)


def _base_response(prepared: dict[str, Any], *, operation: str) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "operation": operation,
        "project_id": prepared["project_id"],
        "batch_id": prepared["batch_id"],
        "slot_id": prepared["slot_id"],
        "queue_id": prepared["queue_id"],
        "slot_index": prepared["slot_index"],
    }


def _result_to_wire(
    result_slot_id: str,
    result: AgentLaunchResult,
    prepared: dict[str, Any],
) -> dict[str, Any]:
    artifacts_timestamp = (
        convert_timestamp_to_artifacts_format(result.timestamp)
        if result.timestamp
        else None
    )
    artifact_dir = None
    if artifacts_timestamp and result.project_name:
        artifact_dir = str(
            Path.home()
            / ".sase"
            / "projects"
            / result.project_name
            / "artifacts"
            / "ace-run"
            / artifacts_timestamp
        )
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "slot_id": result_slot_id,
        "scheduler_slot_id": prepared["slot_id"],
        "pid": result.pid,
        "workspace_claim": {
            "workspace_num": result.workspace_num,
            "workspace_dir": result.workspace_dir,
            "project_file": result.project_file,
            "project_name": result.project_name,
        },
        "artifact_dir": artifact_dir,
        "output_path": result.output_path,
        "workflow_name": result.workflow_name,
        "timestamp": result.timestamp,
        "agent_name": (
            prepared["launch"]["agent_name"] if result_slot_id == "0" else None
        ),
    }


def _failure_payload(exc: Exception) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": _safe_error_message(exc),
        "retryable": False,
    }


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    return message.replace("\x00", "")[:1000]


def _cancel_target_name(request: dict[str, Any], slot: SchedulerHostSlot) -> str | None:
    request_name = _optional_str(request.get("name"))
    if request_name:
        return request_name
    metadata_name = _optional_str(slot.launch_spec.metadata.get("agent_name"))
    if metadata_name:
        return metadata_name
    return planned_name_for_prompt(_prompt_for_launch_spec(slot.launch_spec))


@contextmanager
def _launch_cwd(cwd: str | None) -> Iterator[None]:
    if not cwd:
        yield
        return
    path = Path(cwd).expanduser()
    if not path.is_dir():
        raise SchedulerHostBridgeError(f"launch cwd does not exist: {cwd}")
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SchedulerHostBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise SchedulerHostBridgeError("request JSON must be an object")
    return payload


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchedulerHostBridgeError(f"{key} must be a non-empty string")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


_MODEL_DIRECTIVE_RE = re.compile(r"(?m)^\s*%model(?:[:+(]|\s|$)")


__all__ = [
    "SchedulerHostBridgeError",
    "SchedulerHostLaunchSpec",
    "SchedulerHostSlot",
    "cancel_launch_slot",
    "execute_launch_slot",
    "handle_scheduler_host_bridge",
    "planned_name_for_prompt",
    "prepare_launch_slot",
    "scheduler_host_slot_from_request",
]
