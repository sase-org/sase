"""The request shape and option commands of the BeadSnooze gate.

Everything here defines what a BeadSnooze gate *is*: its constants, the one
request spec the adapter accepts, the option command wrappers, and the result
schemas those commands must emit. Gate validation rebuilds each of these from
the persisted payload and compares, so every helper must stay a pure function
of its arguments.

The spec declares ``presentation.snooze_until``, so the gate service creates
the notification muted and snoozed to the bead's wake instant; the wake needs
no second timer, and the bead stays visible in the panel's Snoozed tab the
whole time it sleeps.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.bead._snooze_gate_preview import (
    bead_snooze_presentation_note,
    render_bead_snooze_preview,
)
from sase.bead.model import CloseRecord, SnoozeRecord, TaskPlusOneEvidence
from sase.bead.snooze_gate_input import (
    resolve_snooze_duration,
    snooze_duration_inputs,
    snooze_duration_result_property,
)
from sase.bead.snooze_time import SnoozeTimeError
from sase.bead.task_gate import (
    apply_task_type_gate_presentation,
    bounded_gate_title,
)
from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    resolve_task_type_gate_display,
    task_type_gate_display_payload,
)

BeadSnoozeAction = Literal["close", "ready", "snooze"]

BEAD_SNOOZE_KIND = "bead_snooze"
BEAD_SNOOZE_CONTINUATION_MODE = "bead_snooze"
BEAD_SNOOZE_QUERY = "close OR ready OR snooze"
BEAD_SNOOZE_CLOSE_OPTION_ID: BeadSnoozeAction = "close"
BEAD_SNOOZE_READY_OPTION_ID: BeadSnoozeAction = "ready"
BEAD_SNOOZE_SNOOZE_OPTION_ID: BeadSnoozeAction = "snooze"
BEAD_SNOOZE_OPTION_IDS: tuple[BeadSnoozeAction, ...] = (
    BEAD_SNOOZE_CLOSE_OPTION_ID,
    BEAD_SNOOZE_READY_OPTION_ID,
    BEAD_SNOOZE_SNOOZE_OPTION_ID,
)
BEAD_SNOOZE_PRIMARY_BRANCH = (BEAD_SNOOZE_CLOSE_OPTION_ID,)
BEAD_SNOOZE_PREVIEW_PATH = "task.md"
BEAD_SNOOZE_COMMAND_PATHS: dict[BeadSnoozeAction, str] = {
    option_id: f"commands/{option_id}" for option_id in BEAD_SNOOZE_OPTION_IDS
}
BEAD_SNOOZE_OPTION_FEEDBACK: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "optional",
    BEAD_SNOOZE_READY_OPTION_ID: "optional",
    # Optional rather than required since the wake time became a declared
    # input: the note is now a reason for the new deferral, not the deferral.
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "optional",
}
BEAD_SNOOZE_READY_NOTE = "Woken from snooze and returned to triage."

_BEAD_SNOOZE_OPTION_LABELS: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "Close",
    BEAD_SNOOZE_READY_OPTION_ID: "Ready",
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "Snooze again",
}
_BEAD_SNOOZE_OPTION_ICONS: dict[BeadSnoozeAction, str] = {
    BEAD_SNOOZE_CLOSE_OPTION_ID: "✕",
    BEAD_SNOOZE_READY_OPTION_ID: "◇",
    BEAD_SNOOZE_SNOOZE_OPTION_ID: "◈",
}


def bead_snooze_presentation(
    *,
    bead_id: str,
    title: str,
    plus_one_count: int,
    until: str,
    reopen_count: int = 0,
    origin_agent: str = "",
    task_type: str = "",
    task_type_display: TaskTypeGateDisplay | None = None,
) -> dict[str, Any]:
    """Return the only presentation mapping a BeadSnooze gate is accepted with."""
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "◈",
        "title": bounded_gate_title(bead_id, title),
        "notes": [
            bead_snooze_presentation_note(
                bead_id,
                title,
                plus_one_count,
                until=until,
                reopen_count=reopen_count,
            )
        ],
        "tags": ["bead", "task"],
        "panel": "beads",
        "panel_icon": "◈",
        "files": [BEAD_SNOOZE_PREVIEW_PATH],
        "preview": BEAD_SNOOZE_PREVIEW_PATH,
        "snooze_until": until,
    }
    if origin_agent:
        presentation["origin_agent"] = origin_agent
    apply_task_type_gate_presentation(
        presentation, task_type=task_type, display=task_type_display
    )
    return presentation


def build_bead_snooze_gate_spec(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    snooze: SnoozeRecord,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
    task_type: str = "",
    task_type_fields: Mapping[str, str] | None = None,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the BeadSnooze adapter."""
    from sase.bead.task_gate import close_record_payload

    origin_agent = created_by.strip()
    evidence = tuple(plus_one_evidence)
    count = len(evidence)
    history = tuple(close_history)
    stored_fields = dict(task_type_fields or {})
    display = resolve_task_type_gate_display(task_type, stored_fields)
    presentation = bead_snooze_presentation(
        bead_id=bead_id,
        title=title,
        plus_one_count=count,
        until=snooze.until,
        reopen_count=len(history),
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
        "snooze": _bead_snooze_payload_record(snooze),
    }
    if display is not None:
        payload["task_type_display"] = task_type_gate_display_payload(display)
    return {
        "schema_version": 3,
        "kind": BEAD_SNOOZE_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": BEAD_SNOOZE_CONTINUATION_MODE,
        "payload": payload,
        "presentation": presentation,
        "query": BEAD_SNOOZE_QUERY,
        "primary_branch": list(BEAD_SNOOZE_PRIMARY_BRANCH),
        "options": [
            bead_snooze_option_spec(option_id) for option_id in BEAD_SNOOZE_OPTION_IDS
        ],
        "resources": [
            *[
                {
                    "path": BEAD_SNOOZE_COMMAND_PATHS[option_id],
                    "role": "command",
                    "content": bead_snooze_gate_command_script(option_id),
                }
                for option_id in BEAD_SNOOZE_OPTION_IDS
            ],
            {
                "path": BEAD_SNOOZE_PREVIEW_PATH,
                "role": "preview",
                "content": render_bead_snooze_preview(
                    bead_id=bead_id,
                    title=title,
                    description=description,
                    notes=notes,
                    snooze=snooze,
                    created_by=origin_agent,
                    created_at=created_at,
                    size=size,
                    refs=refs,
                    plus_one_evidence=evidence,
                    close_history=history,
                    task_type=task_type,
                    task_type_fields=stored_fields,
                    task_type_display=display,
                ),
            },
        ],
        "auto": False,
    }


def bead_snooze_option_spec(option_id: BeadSnoozeAction) -> dict[str, Any]:
    """Return the only spec one BeadSnooze option is accepted with.

    Shared with kind validation, which rebuilds each option from this helper
    rather than restating its shape, so the declared duration input cannot
    drift between what the gate is created with and what is accepted.
    """
    spec: dict[str, Any] = {
        "id": option_id,
        "label": _BEAD_SNOOZE_OPTION_LABELS[option_id],
        "icon": _BEAD_SNOOZE_OPTION_ICONS[option_id],
        "command": {"argv": [BEAD_SNOOZE_COMMAND_PATHS[option_id]]},
        "result_schema": _bead_snooze_result_schema(option_id),
        "feedback": BEAD_SNOOZE_OPTION_FEEDBACK[option_id],
    }
    if option_id == BEAD_SNOOZE_SNOOZE_OPTION_ID:
        spec["inputs"] = snooze_duration_inputs()
    return spec


def _bead_snooze_payload_record(snooze: SnoozeRecord) -> dict[str, Any]:
    """Return the payload projection of one snooze record."""
    return {
        "until": snooze.until,
        "snoozed_at": snooze.snoozed_at,
        "snoozed_by": snooze.snoozed_by,
        "plus_one_target": snooze.plus_one_target,
        "plus_one_baseline": snooze.plus_one_baseline,
        "reason": snooze.reason,
    }


def _bead_snooze_result_schema(action: BeadSnoozeAction) -> dict[str, Any]:
    if action == BEAD_SNOOZE_SNOOZE_OPTION_ID:
        # The re-snooze command echoes back the wake-time expression it
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


def bead_snooze_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the BeadSnooze adapter.

    The wrapper imports from :mod:`sase.bead.snooze_gate` because the script
    text is persisted into every gate bundle and revalidated byte for byte;
    the facade keeps that path stable no matter where the entrypoint lives.
    """
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.snooze_gate import execute_bead_snooze_gate_command\n"
        f"raise SystemExit(execute_bead_snooze_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_bead_snooze_gate_command(option_id: str) -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("bead snooze command input must be an object", file=sys.stderr)
        return 2
    if option_id not in BEAD_SNOOZE_OPTION_IDS:
        print(f"unsupported bead snooze option: {option_id}", file=sys.stderr)
        return 2
    if option_id == BEAD_SNOOZE_SNOOZE_OPTION_ID:
        try:
            duration = resolve_snooze_duration(raw_input)
        except SnoozeTimeError as exc:
            # Failing here leaves the gate pending, so a mistyped duration
            # costs a retry rather than the bead's wake gate.
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"action": option_id, "duration": duration}, sort_keys=True))
        return 0
    if raw_input:
        print("bead snooze command input must be empty", file=sys.stderr)
        return 2
    print(json.dumps({"action": option_id}, sort_keys=True))
    return 0
