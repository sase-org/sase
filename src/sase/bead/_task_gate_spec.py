"""The request shape and option commands of the TaskTriage gate.

Everything here defines what a TaskTriage gate *is*: its constants, the one
request spec the adapter accepts, the option command wrapper, and the result
schema each option must emit. Gate validation rebuilds these from the
persisted payload and compares, so each helper must stay a pure function of
its arguments.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.bead._task_gate_preview import (
    bounded_gate_title,
    render_task_triage_preview,
    task_triage_presentation_note,
)
from sase.bead.model import CloseRecord, TaskPlusOneEvidence
from sase.bead.plus_one_presentation import post_close_plus_one_count
from sase.bead.snooze_gate_input import (
    resolve_snooze_duration,
    snooze_duration_inputs,
    snooze_duration_result_property,
)
from sase.bead.snooze_time import SnoozeTimeError
from sase.notification_gates.entrypoints import (
    gate_command_entrypoint,
    python_gate_command_script,
)
from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    resolve_task_type_gate_display,
    task_type_gate_chip,
    task_type_gate_display_payload,
    task_type_gate_note,
)

TaskTriageAction = Literal["launch", "close", "snooze"]

TASK_TRIAGE_KIND = "task_triage"
TASK_TRIAGE_CONTINUATION_MODE = "task_triage"
TASK_TRIAGE_QUERY = "launch OR close OR snooze"
TASK_TRIAGE_LAUNCH_OPTION_ID: TaskTriageAction = "launch"
TASK_TRIAGE_CLOSE_OPTION_ID: TaskTriageAction = "close"
TASK_TRIAGE_SNOOZE_OPTION_ID: TaskTriageAction = "snooze"
TASK_TRIAGE_OPTION_IDS: tuple[TaskTriageAction, ...] = (
    TASK_TRIAGE_LAUNCH_OPTION_ID,
    TASK_TRIAGE_CLOSE_OPTION_ID,
    TASK_TRIAGE_SNOOZE_OPTION_ID,
)
TASK_TRIAGE_PRIMARY_BRANCH = (TASK_TRIAGE_LAUNCH_OPTION_ID,)
TASK_TRIAGE_PREVIEW_PATH = "task.md"
TASK_TRIAGE_COMMAND_PATHS: dict[TaskTriageAction, str] = {
    option_id: f"commands/{option_id}" for option_id in TASK_TRIAGE_OPTION_IDS
}
TASK_TRIAGE_OPTION_FEEDBACK: dict[TaskTriageAction, str] = {
    TASK_TRIAGE_LAUNCH_OPTION_ID: "optional",
    TASK_TRIAGE_CLOSE_OPTION_ID: "required",
    # Optional rather than required since the wake time became a declared
    # input: the note is now a reason for the deferral, not the deferral.
    TASK_TRIAGE_SNOOZE_OPTION_ID: "optional",
}
TASK_TRIAGE_OPTION_LABELS: dict[TaskTriageAction, str] = {
    TASK_TRIAGE_LAUNCH_OPTION_ID: "Launch",
    TASK_TRIAGE_CLOSE_OPTION_ID: "Close",
    # No longer "(3d, 3d +2)": the label used to teach the free-text
    # convention the duration rode in, which the declared input replaced.
    TASK_TRIAGE_SNOOZE_OPTION_ID: "Snooze",
}
TASK_TRIAGE_OPTION_ICONS: dict[TaskTriageAction, str] = {
    TASK_TRIAGE_LAUNCH_OPTION_ID: "🚀",
    TASK_TRIAGE_CLOSE_OPTION_ID: "✕",
    TASK_TRIAGE_SNOOZE_OPTION_ID: "◈",
}
TASK_TRIAGE_SNOOZE_REASON = "Deferred from triage."


def apply_task_type_gate_presentation(
    presentation: dict[str, Any],
    *,
    task_type: str,
    display: TaskTypeGateDisplay | None,
) -> None:
    """Declare the chip, typed note, and type tag from a frozen display."""
    if display is None:
        return
    presentation["chip"] = task_type_gate_chip(display, task_type)
    presentation["notes"].append(task_type_gate_note(display))
    presentation["tags"].append(task_type)


def task_triage_presentation(
    *,
    bead_id: str,
    title: str,
    plus_one_count: int,
    created_at: str = "",
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    closed_at: str | None = None,
    origin_agent: str = "",
    task_type: str = "",
    task_type_display: TaskTypeGateDisplay | None = None,
) -> dict[str, Any]:
    """Return the only presentation mapping a TaskTriage gate is accepted with."""
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "✦",
        "title": bounded_gate_title(bead_id, title),
        "notes": [
            task_triage_presentation_note(
                bead_id,
                title,
                plus_one_count,
                created_at=created_at,
                reopen_count=len(close_history),
                post_close_count=_post_close_count(plus_one_evidence, closed_at),
            )
        ],
        "tags": ["bead", "task"],
        "panel": "beads",
        "panel_icon": "◈",
        "files": [TASK_TRIAGE_PREVIEW_PATH],
        "preview": TASK_TRIAGE_PREVIEW_PATH,
    }
    if origin_agent:
        presentation["origin_agent"] = origin_agent
    apply_task_type_gate_presentation(
        presentation, task_type=task_type, display=task_type_display
    )
    return presentation


def build_task_triage_gate_spec(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    closed_at: str | None = None,
    task_type: str = "",
    task_type_fields: Mapping[str, str] | None = None,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the TaskTriage adapter."""
    stored_fields = dict(task_type_fields or {})
    origin_agent = created_by.strip()
    evidence = tuple(plus_one_evidence)
    count = len(evidence)
    history = tuple(close_history)
    display = resolve_task_type_gate_display(task_type, stored_fields)
    presentation = task_triage_presentation(
        bead_id=bead_id,
        title=title,
        plus_one_count=count,
        created_at=created_at,
        plus_one_evidence=evidence,
        close_history=history,
        closed_at=closed_at,
        origin_agent=origin_agent,
        task_type=task_type,
        task_type_display=display,
    )
    payload: dict[str, Any] = {
        "bead_id": bead_id,
        "project": project,
        "title": title,
        "created_at": created_at,
        "size": size,
        "refs": list(refs),
        "plus_one_count": count,
        **({"closed_at": closed_at} if closed_at else {}),
        "task_type": task_type,
        "task_type_fields": stored_fields,
        "plus_one_evidence": [
            {
                "timestamp": item.timestamp,
                "reporter": item.reporter,
                "note": item.note,
                "refs": list(item.refs),
                **(
                    {"observed_since": item.observed_since}
                    if item.observed_since
                    else {}
                ),
            }
            for item in evidence
        ],
        "close_history": [close_record_payload(record) for record in history],
    }
    if display is not None:
        payload["task_type_display"] = task_type_gate_display_payload(display)
    return {
        "schema_version": 3,
        "kind": TASK_TRIAGE_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": TASK_TRIAGE_CONTINUATION_MODE,
        "payload": payload,
        "presentation": presentation,
        "query": TASK_TRIAGE_QUERY,
        "primary_branch": list(TASK_TRIAGE_PRIMARY_BRANCH),
        "options": [
            task_triage_option_spec(option_id) for option_id in TASK_TRIAGE_OPTION_IDS
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
                    created_at=created_at,
                    size=size,
                    refs=refs,
                    plus_one_evidence=evidence,
                    close_history=history,
                    closed_at=closed_at,
                    task_type=task_type,
                    task_type_fields=stored_fields,
                    task_type_display=display,
                ),
            },
        ],
        "auto": False,
    }


def task_triage_option_spec(option_id: TaskTriageAction) -> dict[str, Any]:
    """Return the only spec one TaskTriage option is accepted with.

    Shared with kind validation, which rebuilds each option from this helper
    rather than restating its shape, so the declared duration input cannot
    drift between what the gate is created with and what is accepted.
    """
    spec: dict[str, Any] = {
        "id": option_id,
        "label": TASK_TRIAGE_OPTION_LABELS[option_id],
        "icon": TASK_TRIAGE_OPTION_ICONS[option_id],
        "command": {"argv": [TASK_TRIAGE_COMMAND_PATHS[option_id]]},
        "result_schema": task_triage_result_schema(option_id),
        "feedback": TASK_TRIAGE_OPTION_FEEDBACK[option_id],
    }
    if option_id == TASK_TRIAGE_SNOOZE_OPTION_ID:
        spec["inputs"] = snooze_duration_inputs()
    return spec


def _post_close_count(
    evidence: Sequence[TaskPlusOneEvidence], closed_at: str | None
) -> int:
    if not closed_at:
        return 0
    from sase.bead.model import Issue, IssueType, Status

    issue = Issue(
        "preview",
        "",
        status=Status.CLOSED,
        issue_type=IssueType.TASK,
        closed_at=closed_at,
        plus_one_evidence=list(evidence),
    )
    return post_close_plus_one_count(issue)


def close_record_payload(record: CloseRecord) -> dict[str, Any]:
    """Return the gate-payload projection of one close record.

    Shared with the BeadSnooze gate, whose payload carries the same close
    history so both gates present a previously-closed task the same way.
    """
    return {
        "closed_at": record.closed_at,
        "close_reason": record.close_reason,
        "resolution": record.resolution.value if record.resolution else None,
        "reopened_at": record.reopened_at,
        "reopened_via": record.reopened_via.value,
        "reopened_by": record.reopened_by,
    }


def task_triage_result_schema(action: TaskTriageAction) -> dict[str, Any]:
    if action == TASK_TRIAGE_SNOOZE_OPTION_ID:
        # The snooze command echoes back the wake-time expression it
        # validated, so the host effect resolves the instant a reviewer
        # actually chose rather than re-reading a free-text note.
        return {
            "type": "object",
            "required": ["action", "duration"],
            "properties": {
                "action": {"const": action},
                "duration": snooze_duration_result_property(),
            },
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": action}},
        "additionalProperties": False,
    }


def task_triage_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the TaskTriage adapter.

    The wrapper imports from :mod:`sase.bead.task_gate` because the script text
    is persisted into every gate bundle and revalidated byte for byte; the
    facade keeps that path stable no matter where the entrypoint lives.
    """
    return python_gate_command_script(
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
    if option_id not in TASK_TRIAGE_OPTION_IDS:
        print(f"unsupported task triage option: {option_id}", file=sys.stderr)
        return 2
    if option_id == TASK_TRIAGE_SNOOZE_OPTION_ID:
        try:
            duration = resolve_snooze_duration(raw_input)
        except SnoozeTimeError as exc:
            # Failing here leaves the gate pending, so a mistyped duration
            # costs a retry rather than the task's triage gate.
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"action": option_id, "duration": duration}, sort_keys=True))
        return 0
    if raw_input:
        print("task triage command input must be empty", file=sys.stderr)
        return 2
    print(json.dumps({"action": option_id}, sort_keys=True))
    return 0
