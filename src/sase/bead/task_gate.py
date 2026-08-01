"""Trusted notification-gate contract for standalone task-bead triage."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.task_launch import TaskLaunchOrigin
    from sase.tasks.models import BackgroundTask

TaskTriageAction = Literal["launch", "close"]

TASK_TRIAGE_KIND = "task_triage"
TASK_TRIAGE_CONTINUATION_MODE = "task_triage"
TASK_TRIAGE_QUERY = "launch OR close"
TASK_TRIAGE_LAUNCH_OPTION_ID: TaskTriageAction = "launch"
TASK_TRIAGE_CLOSE_OPTION_ID: TaskTriageAction = "close"
TASK_TRIAGE_OPTION_IDS: tuple[TaskTriageAction, ...] = (
    TASK_TRIAGE_LAUNCH_OPTION_ID,
    TASK_TRIAGE_CLOSE_OPTION_ID,
)
TASK_TRIAGE_PRIMARY_BRANCH = (TASK_TRIAGE_LAUNCH_OPTION_ID,)
TASK_TRIAGE_PREVIEW_PATH = "task.md"
TASK_TRIAGE_COMMAND_PATHS: dict[TaskTriageAction, str] = {
    option_id: f"commands/{option_id}" for option_id in TASK_TRIAGE_OPTION_IDS
}


@dataclass(frozen=True)
class _TaskTriageResponse:
    """Trusted task identity and decision translated from a persisted gate."""

    bead_id: str
    project: str
    title: str
    action: TaskTriageAction
    feedback: str | None
    source: str


def create_task_triage_gate(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    producer: Mapping[str, Any] | None = None,
) -> Any:
    """Create one human-only triage gate for a ready standalone task bead."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        _build_task_triage_gate_spec(
            request_id=request_id,
            bead_id=bead_id,
            project=project,
            title=title,
            description=description,
            notes=notes,
            created_by=created_by,
            producer=producer,
        )
    )


def _build_task_triage_gate_spec(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the TaskTriage adapter."""
    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    origin_agent = created_by.strip()
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "✦",
        "notes": [f"{bead_id} — {title}"],
        "tags": ["bead", "task"],
        "panel": "beads",
        "files": [TASK_TRIAGE_PREVIEW_PATH],
        "preview": TASK_TRIAGE_PREVIEW_PATH,
    }
    if origin_agent:
        presentation["origin_agent"] = origin_agent
    return {
        "schema_version": 3,
        "kind": TASK_TRIAGE_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": TASK_TRIAGE_CONTINUATION_MODE,
        "payload": {
            "bead_id": bead_id,
            "project": project,
            "title": title,
        },
        "presentation": presentation,
        "query": TASK_TRIAGE_QUERY,
        "primary_branch": list(TASK_TRIAGE_PRIMARY_BRANCH),
        "options": [
            {
                "id": TASK_TRIAGE_LAUNCH_OPTION_ID,
                "label": "Launch",
                "icon": "🚀",
                "command": {
                    "argv": [TASK_TRIAGE_COMMAND_PATHS[TASK_TRIAGE_LAUNCH_OPTION_ID]]
                },
                "input_schema": empty_input_schema,
                "result_schema": task_triage_result_schema(
                    TASK_TRIAGE_LAUNCH_OPTION_ID
                ),
                "feedback": "optional",
            },
            {
                "id": TASK_TRIAGE_CLOSE_OPTION_ID,
                "label": "Close",
                "icon": "✕",
                "command": {
                    "argv": [TASK_TRIAGE_COMMAND_PATHS[TASK_TRIAGE_CLOSE_OPTION_ID]]
                },
                "input_schema": empty_input_schema,
                "result_schema": task_triage_result_schema(TASK_TRIAGE_CLOSE_OPTION_ID),
                "feedback": "required",
            },
        ],
        "resources": [
            *[
                {
                    "path": TASK_TRIAGE_COMMAND_PATHS[option_id],
                    "role": "command",
                    "content": task_triage_gate_command_script(option_id),
                }
                for option_id in TASK_TRIAGE_OPTION_IDS
            ],
            {
                "path": TASK_TRIAGE_PREVIEW_PATH,
                "role": "preview",
                "content": render_task_triage_preview(
                    bead_id=bead_id,
                    title=title,
                    description=description,
                    notes=notes,
                    created_by=origin_agent,
                ),
            },
        ],
        "auto": False,
    }


def render_task_triage_preview(
    *,
    bead_id: str,
    title: str,
    description: str,
    notes: str,
    created_by: str = "",
) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients."""
    description_text = description.strip() or "_No description._"
    notes_text = notes.strip() or "_No notes._"
    filer = f"**Filed by:** `@{created_by}`\n\n" if created_by else ""
    return (
        f"# {bead_id} — {title}\n\n"
        f"{filer}"
        f"## Description\n\n{description_text}\n\n"
        f"## Notes\n\n{notes_text}\n"
    )


def task_triage_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the TaskTriage adapter."""
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.task_gate import execute_task_triage_gate_command\n"
        f"raise SystemExit(execute_task_triage_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_task_triage_gate_command(option_id: str) -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("task triage command input must be an object", file=sys.stderr)
        return 2
    if raw_input:
        print("task triage command input must be empty", file=sys.stderr)
        return 2
    if option_id not in TASK_TRIAGE_OPTION_IDS:
        print(f"unsupported task triage option: {option_id}", file=sys.stderr)
        return 2
    print(json.dumps({"action": option_id}, sort_keys=True))
    return 0


def translate_task_triage_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> _TaskTriageResponse:
    """Translate one persisted TaskTriage response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != TASK_TRIAGE_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a task triage gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "task triage request payload is missing",
        )
    bead_id, project, title = _task_identity_from_payload(payload)

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] not in TASK_TRIAGE_OPTION_IDS
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response must select exactly launch or close",
        )
    action = raw_selected[0]
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == action
        ),
        None,
    )
    if not isinstance(result, Mapping) or result.get("action") != action:
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "task triage response result does not match its selected action",
        )

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    if action == TASK_TRIAGE_CLOSE_OPTION_ID and feedback is None:
        raise GateError(
            "invalid_response",
            "feedback",
            "closing a task triage gate requires a reason",
        )
    source = response.get("source")
    return _TaskTriageResponse(
        bead_id=bead_id,
        project=project,
        title=title,
        action=cast(TaskTriageAction, action),
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
    )


def _resolve_task_triage_project_cwd(project: str) -> Path:
    """Resolve an explicit ProjectSpec key to its canonical primary checkout."""
    from sase.bead.task_launch import resolve_task_launch_cwd_for_project

    try:
        return resolve_task_launch_cwd_for_project(project)
    except (FileNotFoundError, ValueError) as exc:
        raise GateError(
            "invalid_task_project",
            "payload.project",
            str(exc),
        ) from exc


def _find_pending_task_triage(project: str, bead_id: str) -> str | None:
    """Return the pending TaskTriage request matching trusted payload fields."""
    from sase.notification_gates.durability import read_json_object
    from sase.notification_gates.paths import interaction_requests_dir

    kind_dir = interaction_requests_dir() / TASK_TRIAGE_KIND
    try:
        bundles = sorted(kind_dir.iterdir())
    except FileNotFoundError:
        return None
    except OSError:
        return None
    for bundle in bundles:
        if not bundle.is_dir():
            continue
        if (bundle / "response.json").exists() or (
            bundle / "cancellation.json"
        ).exists():
            continue
        try:
            envelope = read_json_object(bundle / "request.json")
        except GateError:
            continue
        if envelope.get("kind") != TASK_TRIAGE_KIND:
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if payload.get("project") != project or payload.get("bead_id") != bead_id:
            continue
        request_id = envelope.get("request_id")
        if isinstance(request_id, str) and request_id:
            return request_id
    return None


def cancel_task_triage(
    project: str,
    bead_id: str,
    *,
    reason: str,
    source: str = "ace",
) -> bool:
    """Cancel a pending task triage and settle its notification."""
    request_id = _find_pending_task_triage(project, bead_id)
    if request_id is None:
        return False
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.paths import bundle_paths

    try:
        cancel_gate(
            bundle_paths(TASK_TRIAGE_KIND, request_id).root,
            reason=reason,
            source=source,
        )
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def launch_task_triage(
    decision: _TaskTriageResponse,
    *,
    origin: TaskLaunchOrigin | None = None,
) -> BackgroundTask:
    """Submit or reuse the detached task launch selected by a human."""
    if decision.action != TASK_TRIAGE_LAUNCH_OPTION_ID:
        raise GateError(
            "invalid_task_action",
            decision.action,
            "task triage launch helper requires the launch action",
        )
    from sase.bead.task_launch import (
        submit_task_launch_task,
        task_launch_origin_from_gate_source,
    )

    cwd = _resolve_task_triage_project_cwd(decision.project)
    return submit_task_launch_task(
        decision.bead_id,
        cwd=cwd,
        feedback=decision.feedback,
        origin=(
            origin
            if origin is not None
            else task_launch_origin_from_gate_source(decision.source)
        ),
    )


def close_task_triage(decision: _TaskTriageResponse) -> None:
    """Cancel the selected task using the CLI's locked commit/push semantics."""
    if decision.action != TASK_TRIAGE_CLOSE_OPTION_ID or decision.feedback is None:
        raise GateError(
            "invalid_task_action",
            decision.action,
            "task triage close helper requires close with a reason",
        )
    from sase.bead.cli_common import auto_commit_bead_store, bead_store_mutation
    from sase.bead.mutation_commit import close_mutation_commit_message

    cwd = _resolve_task_triage_project_cwd(decision.project)
    with bead_store_mutation(auto_commit_bead_store, cwd=cwd) as mutation:
        mutation.project.close(
            [decision.bead_id],
            reason=decision.feedback,
            resolution="canceled",
        )
        outcome = mutation.project.last_mutation_outcome
        commit_message = close_mutation_commit_message(
            closed_ids=_outcome_ids(outcome, "closed_ids"),
            cascade_closed_ids=_outcome_ids(outcome, "cascade_closed_ids"),
            noted_ids=_outcome_ids(outcome, "noted_ids"),
        )
        if commit_message is not None:
            mutation.commit(commit_message)


def task_triage_result_schema(action: TaskTriageAction) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": action}},
        "additionalProperties": False,
    }


def _task_identity_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, str, str]:
    values: list[str] = []
    for field in ("bead_id", "project", "title"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GateError(
                "invalid_task_payload",
                f"payload.{field}",
                f"task triage payload requires {field}",
            )
        values.append(value)
    return values[0], values[1], values[2]


def _outcome_ids(outcome: Mapping[str, Any], field: str) -> list[str]:
    raw = outcome.get(field)
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw]


__all__ = [
    "TASK_TRIAGE_CLOSE_OPTION_ID",
    "TASK_TRIAGE_COMMAND_PATHS",
    "TASK_TRIAGE_CONTINUATION_MODE",
    "TASK_TRIAGE_KIND",
    "TASK_TRIAGE_LAUNCH_OPTION_ID",
    "TASK_TRIAGE_OPTION_IDS",
    "TASK_TRIAGE_PREVIEW_PATH",
    "TASK_TRIAGE_PRIMARY_BRANCH",
    "TASK_TRIAGE_QUERY",
    "TaskTriageAction",
    "cancel_task_triage",
    "close_task_triage",
    "create_task_triage_gate",
    "execute_task_triage_gate_command",
    "launch_task_triage",
    "render_task_triage_preview",
    "task_triage_gate_command_script",
    "task_triage_result_schema",
    "translate_task_triage_response",
]
