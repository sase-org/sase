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
        "state": state,
        "artifacts_dir": str(path.parent),
        "event": event,
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
    payload = {
        "action_kind": action_kind,
        "response_path": str(path),
        "response_json": response_json,
        "workflow_id": workflow_id,
        "notification_id": notification_id,
        "state": "already_handled",
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
    "write_action_response_once",
    "write_workflow_state",
]
