"""Daemon-backed workflow source-file write helpers with direct fallback."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.write_facade import DaemonWriteResult, write_or_fallback

MUTATION_WIRE_SCHEMA_VERSION = 1
WORKFLOW_WRITE_CAPABILITY = "workflows.write"


def write_workflow_state(
    state_path: str | Path,
    state: dict[str, Any],
    *,
    direct_writer: Callable[[], None],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
    event: str = "run_updated",
) -> DaemonWriteResult[None]:
    """Write ``workflow_state.json`` through the daemon when available."""

    path = Path(state_path).expanduser()
    content = _json_content(state)
    export_plan = _atomic_json_export_plan(
        path,
        content,
        repair_context={"domain": "workflow", "file": "workflow_state.json"},
        expected_fingerprint=_current_fingerprint(path),
    )
    payload = {
        "workflow_id": _workflow_id_from_artifacts_dir(path.parent),
        "state": state,
        "artifacts_dir": str(path.parent),
        "event": event,
        "cause": _workflow_cause(event),
        "task": _workflow_task(
            _workflow_id_from_artifacts_dir(path.parent),
            event,
            str(state.get("status") or "running"),
            step_index=state.get("current_step_index"),
        ),
    }
    return write_or_fallback(
        "workflow.state",
        args=args,
        client=client,
        required_capability=WORKFLOW_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "workflow.state",
            payload,
            idempotency_key=_idempotency_key(
                "workflow.state", str(path), payload, export_plan["content_sha256"]
            ),
            source_exports=[export_plan],
        ),
        direct_writer=direct_writer,
    )


def write_action_response_once(
    response_path: str | Path,
    response_json: dict[str, Any],
    *,
    action_kind: str,
    notification_id: str | None,
    direct_writer: Callable[[], None] | None = None,
    workflow_id: str | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[None]:
    """Create a plan/HITL/question response file exactly once."""

    path = Path(response_path).expanduser()
    resolved_workflow_id = workflow_id or _workflow_id_from_artifacts_dir(path.parent)
    payload = {
        "action_kind": action_kind,
        "response_path": str(path),
        "response_json": response_json,
        "workflow_id": resolved_workflow_id,
        "notification_id": notification_id,
        "state": "already_handled",
        "cause": _workflow_cause(
            "hitl_response" if action_kind == "hitl" else "action_response",
            reason=action_kind,
        ),
        "task": _workflow_task(
            resolved_workflow_id,
            "hitl_response" if action_kind == "hitl" else "action_response",
            "completed",
        ),
    }
    return write_or_fallback(
        "workflow.action_response",
        args=args,
        client=client,
        required_capability=WORKFLOW_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "workflow.action_response",
            payload,
            idempotency_key=_idempotency_key(
                "workflow.action_response", str(path), payload
            ),
        ),
        direct_writer=direct_writer
        or (lambda: _write_json_once_direct(path, response_json, notification_id)),
    )


def write_hitl_request(
    request_path: str | Path,
    request_json: dict[str, Any],
    *,
    direct_writer: Callable[[], None],
    workflow_id: str | None = None,
    reason: str | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[None]:
    """Materialize a HITL request through daemon workflow writes."""

    path = Path(request_path).expanduser()
    resolved_workflow_id = workflow_id or _workflow_id_from_artifacts_dir(path.parent)
    content = _json_content(request_json)
    export_plan = _atomic_json_export_plan(
        path,
        content,
        repair_context={"domain": "workflow", "file": "hitl_request.json"},
        expected_fingerprint=_current_fingerprint(path),
    )
    payload = {
        "workflow_id": resolved_workflow_id,
        "request_path": str(path),
        "request_json": request_json,
        "reason": reason,
        "cause": _workflow_cause("hitl_pause", reason=reason),
        "task": _workflow_task(resolved_workflow_id, "hitl_pause", "waiting"),
    }
    return write_or_fallback(
        "workflow.hitl_request",
        args=args,
        client=client,
        required_capability=WORKFLOW_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "workflow.hitl_request",
            payload,
            idempotency_key=_idempotency_key(
                "workflow.hitl_request", str(path), payload
            ),
            source_exports=[export_plan],
        ),
        direct_writer=direct_writer,
    )


def write_workflow_step_transition(
    artifacts_dir: str | Path,
    *,
    workflow_name: str,
    step_name: str,
    status: str,
    step_index: int | None,
    step_type: str,
    step_source: str | None = None,
    output: Any = None,
    output_types: dict[str, str] | None = None,
    error: str | None = None,
    traceback: str | None = None,
    log_summary: str | None = None,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonWriteResult[None]:
    """Record a durable scheduler-visible workflow step transition."""

    artifacts_path = Path(artifacts_dir).expanduser()
    workflow_id = _workflow_id_from_artifacts_dir(artifacts_path)
    resolved_step_index = int(step_index or 0)
    step_id = _workflow_step_id(workflow_id, resolved_step_index, step_name)
    step = {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "step_index": resolved_step_index,
        "name": step_name,
        "status": status,
        "step_type": step_type,
        "step_source": step_source,
        "artifacts_dir": str(artifacts_path),
        "output": output,
        "output_types": output_types,
        "error": error,
        "traceback": traceback,
        "marker": {
            "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
            "workflow_name": workflow_name,
            "step_name": step_name,
            "status": status,
            "step_type": step_type,
            "step_source": step_source,
            "step_index": resolved_step_index,
            "artifacts_dir": str(artifacts_path),
            "output": output,
            "output_types": output_types,
            "error": error,
            "traceback": traceback,
        },
    }
    cause = _workflow_cause("step_transition", reason=step_id)
    payload = {
        "workflow_id": workflow_id,
        "step": step,
        "cause": cause,
        "task": _workflow_task(
            workflow_id,
            "step_transition",
            status,
            step_id=step_id,
            step_index=resolved_step_index,
            log_summary=log_summary,
        ),
    }
    return write_or_fallback(
        "workflow.step_transition",
        args=args,
        client=client,
        required_capability=WORKFLOW_WRITE_CAPABILITY,
        daemon_writer=lambda daemon: _write_void(
            daemon,
            "workflow.step_transition",
            payload,
            idempotency_key=_idempotency_key(
                "workflow.step_transition", workflow_id, step_id, status, payload
            ),
        ),
        direct_writer=lambda: None,
    )


def _write_void(
    daemon: LocalDaemonClient,
    surface: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    source_exports: list[dict[str, Any]] | None = None,
) -> None:
    daemon.write(
        surface,
        {
            "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
            "project_id": _project_id(),
            "idempotency_key": idempotency_key,
            "actor": _actor(),
            "payload": payload,
            "source_exports": source_exports or [],
        },
    )


def _atomic_json_export_plan(
    path: Path,
    content: str,
    *,
    repair_context: dict[str, Any],
    expected_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "target_path": str(path),
        "kind": "atomic_json",
        "expected_fingerprint": expected_fingerprint,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_utf8": content,
        "repair_context": repair_context,
    }


def _current_fingerprint(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "file_size": len(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_json_once_direct(
    path: Path,
    response_json: dict[str, Any],
    notification_id: str | None,
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        from sase.integrations._mobile_notification_models import (
            MobilePlanActionError,
        )

        raise MobilePlanActionError(
            "conflict_already_handled",
            notification_id or str(path),
            "response already exists",
        ) from exc


def _json_content(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, default=str) + "\n"


def _idempotency_key(surface: str, *parts: Any) -> str:
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{surface}:{digest}"


def _workflow_id_from_artifacts_dir(path: Path) -> str:
    name = path.expanduser().name
    return name or "workflow"


def _workflow_step_id(workflow_id: str, step_index: int, step_name: str) -> str:
    return f"{workflow_id}:step:{step_index}:{step_name}"


def _workflow_cause(kind: str, *, reason: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "kind": kind,
        "reason": reason,
    }


def _workflow_task(
    workflow_id: str,
    task_kind: str,
    status: str,
    *,
    step_id: str | None = None,
    step_index: int | None = None,
    log_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "task_id": _workflow_task_id(workflow_id, task_kind, step_id),
        "workflow_id": workflow_id,
        "task_kind": task_kind,
        "status": _task_status(status),
        "step_id": step_id,
        "step_index": step_index,
        "log_summary": log_summary,
    }


def _workflow_task_id(
    workflow_id: str,
    task_kind: str,
    step_id: str | None = None,
) -> str:
    return "workflow-task:{}:{}:{}".format(
        _sanitize_task_part(workflow_id),
        _sanitize_task_part(task_kind),
        _sanitize_task_part(step_id or "workflow"),
    )


def _task_status(status: str) -> str:
    if status in {"completed", "failed", "skipped"}:
        return status
    if status in {"waiting", "waiting_hitl", "paused"}:
        return "waiting"
    return "running"


def _sanitize_task_part(value: str) -> str:
    sanitized = "".join(
        char if char.isalnum() or char in "-_." else "_" for char in value
    )
    return sanitized or "unknown"


def _actor() -> dict[str, Any]:
    return {
        "schema_version": MUTATION_WIRE_SCHEMA_VERSION,
        "actor_type": "python",
        "name": "sase-workflow",
    }


def _project_id() -> str:
    return os.environ.get("SASE_PROJECT_NAME") or "home"


__all__ = [
    "WORKFLOW_WRITE_CAPABILITY",
    "write_hitl_request",
    "write_action_response_once",
    "write_workflow_step_transition",
    "write_workflow_state",
]
