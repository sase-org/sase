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
from sase.notification_gates.entrypoints import gate_command_entrypoint

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
    TASK_TRIAGE_SNOOZE_OPTION_ID: "required",
}
TASK_TRIAGE_OPTION_LABELS: dict[TaskTriageAction, str] = {
    TASK_TRIAGE_LAUNCH_OPTION_ID: "Launch",
    TASK_TRIAGE_CLOSE_OPTION_ID: "Close",
    TASK_TRIAGE_SNOOZE_OPTION_ID: "Snooze (3d, 3d +2)",
}
TASK_TRIAGE_OPTION_ICONS: dict[TaskTriageAction, str] = {
    TASK_TRIAGE_LAUNCH_OPTION_ID: "🚀",
    TASK_TRIAGE_CLOSE_OPTION_ID: "✕",
    TASK_TRIAGE_SNOOZE_OPTION_ID: "◈",
}
TASK_TRIAGE_SNOOZE_REASON = "Deferred from triage."


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
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the TaskTriage adapter."""
    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    origin_agent = created_by.strip()
    evidence = tuple(plus_one_evidence)
    count = len(evidence)
    history = tuple(close_history)
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "✦",
        "title": bounded_gate_title(bead_id, title),
        "notes": [
            task_triage_presentation_note(
                bead_id,
                title,
                count,
                created_at=created_at,
                reopen_count=len(history),
            )
        ],
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
            "created_at": created_at,
            "size": size,
            "refs": list(refs),
            "plus_one_count": count,
            "plus_one_evidence": [
                {
                    "timestamp": item.timestamp,
                    "reporter": item.reporter,
                    "note": item.note,
                    "refs": list(item.refs),
                }
                for item in evidence
            ],
            "close_history": [close_record_payload(record) for record in history],
        },
        "presentation": presentation,
        "query": TASK_TRIAGE_QUERY,
        "primary_branch": list(TASK_TRIAGE_PRIMARY_BRANCH),
        "options": [
            {
                "id": option_id,
                "label": TASK_TRIAGE_OPTION_LABELS[option_id],
                "icon": TASK_TRIAGE_OPTION_ICONS[option_id],
                "command": {"argv": [TASK_TRIAGE_COMMAND_PATHS[option_id]]},
                "input_schema": empty_input_schema,
                "result_schema": task_triage_result_schema(option_id),
                "feedback": TASK_TRIAGE_OPTION_FEEDBACK[option_id],
            }
            for option_id in TASK_TRIAGE_OPTION_IDS
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
                ),
            },
        ],
        "auto": False,
    }


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
