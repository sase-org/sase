"""The request shape and option commands of the FlagTriage gate.

Everything here defines what a FlagTriage gate *is*: its constants, the one
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

from sase.bead._flag_gate_preview import (
    flag_triage_presentation_note,
    render_flag_triage_preview,
)
from sase.bead.flag_fields import FLAG_TASK_TYPE
from sase.bead.flag_gate_input import (
    flag_triage_extend_inputs,
    resolve_flag_triage_extend,
)
from sase.bead.model import FlagRecord
from sase.bead.snooze_time import SnoozeTimeError
from sase.bead.task_gate import apply_task_type_gate_presentation, bounded_gate_title
from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    resolve_task_type_gate_display,
    task_type_gate_display_payload,
)

FlagTriageAction = Literal["remove", "extend", "keep", "close"]

FLAG_TRIAGE_KIND = "flag_triage"
FLAG_TRIAGE_CONTINUATION_MODE = "flag_triage"
FLAG_TRIAGE_QUERY = "remove OR extend OR keep OR close"
FLAG_TRIAGE_REMOVE_OPTION_ID: FlagTriageAction = "remove"
FLAG_TRIAGE_EXTEND_OPTION_ID: FlagTriageAction = "extend"
FLAG_TRIAGE_KEEP_OPTION_ID: FlagTriageAction = "keep"
FLAG_TRIAGE_CLOSE_OPTION_ID: FlagTriageAction = "close"
FLAG_TRIAGE_OPTION_IDS: tuple[FlagTriageAction, ...] = (
    FLAG_TRIAGE_REMOVE_OPTION_ID,
    FLAG_TRIAGE_EXTEND_OPTION_ID,
    FLAG_TRIAGE_KEEP_OPTION_ID,
    FLAG_TRIAGE_CLOSE_OPTION_ID,
)
FLAG_TRIAGE_PRIMARY_BRANCH = (FLAG_TRIAGE_REMOVE_OPTION_ID,)
FLAG_TRIAGE_PREVIEW_PATH = "flag.md"
FLAG_TRIAGE_COMMAND_PATHS: dict[FlagTriageAction, str] = {
    option_id: f"commands/{option_id}" for option_id in FLAG_TRIAGE_OPTION_IDS
}
FLAG_TRIAGE_OPTION_FEEDBACK: dict[FlagTriageAction, str] = {
    FLAG_TRIAGE_REMOVE_OPTION_ID: "optional",
    FLAG_TRIAGE_EXTEND_OPTION_ID: "required",
    FLAG_TRIAGE_KEEP_OPTION_ID: "required",
    FLAG_TRIAGE_CLOSE_OPTION_ID: "required",
}
FLAG_TRIAGE_OPTION_LABELS: dict[FlagTriageAction, str] = {
    FLAG_TRIAGE_REMOVE_OPTION_ID: "Remove",
    FLAG_TRIAGE_EXTEND_OPTION_ID: "Extend",
    FLAG_TRIAGE_KEEP_OPTION_ID: "Keep",
    FLAG_TRIAGE_CLOSE_OPTION_ID: "Close",
}
FLAG_TRIAGE_OPTION_ICONS: dict[FlagTriageAction, str] = {
    FLAG_TRIAGE_REMOVE_OPTION_ID: "🚀",
    FLAG_TRIAGE_EXTEND_OPTION_ID: "⏳",
    FLAG_TRIAGE_KEEP_OPTION_ID: "⚑",
    FLAG_TRIAGE_CLOSE_OPTION_ID: "✕",
}
_FLAG_TRIAGE_WINNER_FIELD_ID = "winner"
_FLAG_TRIAGE_WINNER_CHOICES = ("enabled", "disabled")


def flag_triage_flag_payload(flag: FlagRecord, kind: str) -> dict[str, str]:
    """Return the persisted flag identity block: key, kind, and thresholds."""
    return {
        "key": flag.key,
        "kind": kind,
        "remove_by_date": flag.remove_by_date,
        "remove_by_release": flag.remove_by_release,
    }


def flag_triage_presentation(
    *,
    bead_id: str,
    title: str,
    flag: FlagRecord,
    due_as_of: str,
    release: str,
    origin_agent: str = "",
    task_type: str = "",
    task_type_display: TaskTypeGateDisplay | None = None,
) -> dict[str, Any]:
    """Return the only presentation mapping a FlagTriage gate is accepted with."""
    presentation: dict[str, Any] = {
        "sender": "bead",
        "icon": "⚑",
        "title": bounded_gate_title(bead_id, title),
        "notes": [
            flag_triage_presentation_note(
                bead_id,
                title,
                flag,
                due_as_of=due_as_of,
                release=release,
            )
        ],
        "tags": ["bead", "task"],
        "panel": "beads",
        "panel_icon": "⚑",
        "files": [FLAG_TRIAGE_PREVIEW_PATH],
        "preview": FLAG_TRIAGE_PREVIEW_PATH,
    }
    if origin_agent:
        presentation["origin_agent"] = origin_agent
    apply_task_type_gate_presentation(
        presentation, task_type=task_type, display=task_type_display
    )
    return presentation


def build_flag_triage_gate_spec(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    flag: FlagRecord,
    due_state: str,
    due_as_of: str,
    release: str,
    definition: Mapping[str, str] | None = None,
    description: str = "",
    notes: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    kind: str = "",
    task_type: str = FLAG_TASK_TYPE,
    task_type_fields: Mapping[str, str] | None = None,
    producer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the FlagTriage adapter."""
    stored_fields = dict(task_type_fields or {})
    resolved_kind = (
        kind or stored_fields.get("kind", "") or _definition_kind(definition)
    )
    origin_agent = created_by.strip()
    display = resolve_task_type_gate_display(task_type, stored_fields)
    presentation = flag_triage_presentation(
        bead_id=bead_id,
        title=title,
        flag=flag,
        due_as_of=due_as_of,
        release=release,
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
        "flag": flag_triage_flag_payload(flag, resolved_kind),
        "due_state": due_state,
        "due_as_of": due_as_of,
        "release": release,
        "definition": dict(definition) if definition is not None else None,
        "task_type": task_type,
        "task_type_fields": stored_fields,
    }
    if display is not None:
        payload["task_type_display"] = task_type_gate_display_payload(display)
    return {
        "schema_version": 3,
        "kind": FLAG_TRIAGE_KIND,
        "request_id": request_id,
        "producer": dict(producer or {}),
        "continuation_mode": FLAG_TRIAGE_CONTINUATION_MODE,
        "payload": payload,
        "presentation": presentation,
        "query": FLAG_TRIAGE_QUERY,
        "primary_branch": list(FLAG_TRIAGE_PRIMARY_BRANCH),
        "options": [
            flag_triage_option_spec(option_id) for option_id in FLAG_TRIAGE_OPTION_IDS
        ],
        "resources": [
            *[
                {
                    "path": FLAG_TRIAGE_COMMAND_PATHS[option_id],
                    "role": "command",
                    "content": flag_triage_gate_command_script(option_id),
                }
                for option_id in FLAG_TRIAGE_OPTION_IDS
            ],
            {
                "path": FLAG_TRIAGE_PREVIEW_PATH,
                "role": "preview",
                "content": render_flag_triage_preview(
                    bead_id=bead_id,
                    title=title,
                    description=description,
                    notes=notes,
                    flag=flag,
                    due_as_of=due_as_of,
                    release=release,
                    definition=definition,
                    kind=resolved_kind,
                    created_by=origin_agent,
                    created_at=created_at,
                    size=size,
                    task_type=task_type,
                    task_type_fields=stored_fields,
                    task_type_display=display,
                ),
            },
        ],
        "auto": False,
    }


def _definition_kind(definition: Mapping[str, str] | None) -> str:
    if definition is None:
        return ""
    return definition.get("kind", "")


def flag_triage_option_spec(option_id: FlagTriageAction) -> dict[str, Any]:
    """Return the only spec one FlagTriage option is accepted with.

    Shared with kind validation, which rebuilds each option from this helper
    rather than restating its shape, so a declared input cannot drift between
    what the gate is created with and what is accepted.
    """
    spec: dict[str, Any] = {
        "id": option_id,
        "label": FLAG_TRIAGE_OPTION_LABELS[option_id],
        "icon": FLAG_TRIAGE_OPTION_ICONS[option_id],
        "command": {"argv": [FLAG_TRIAGE_COMMAND_PATHS[option_id]]},
        "result_schema": flag_triage_result_schema(option_id),
        "feedback": FLAG_TRIAGE_OPTION_FEEDBACK[option_id],
    }
    if option_id == FLAG_TRIAGE_REMOVE_OPTION_ID:
        spec["inputs"] = _flag_triage_winner_inputs()
    elif option_id == FLAG_TRIAGE_EXTEND_OPTION_ID:
        spec["inputs"] = flag_triage_extend_inputs()
    return spec


def _flag_triage_winner_inputs() -> list[dict[str, Any]]:
    return [
        {
            "id": _FLAG_TRIAGE_WINNER_FIELD_ID,
            "label": "Winning branch",
            "type": "enum",
            "required": True,
            "choices": list(_FLAG_TRIAGE_WINNER_CHOICES),
        },
    ]


def flag_triage_result_schema(action: FlagTriageAction) -> dict[str, Any]:
    if action == FLAG_TRIAGE_REMOVE_OPTION_ID:
        # The remove command echoes back the winning branch it validated, so
        # the host effect acts on the value a reviewer actually chose rather
        # than re-reading free text.
        return {
            "type": "object",
            "required": ["action", "winner"],
            "properties": {
                "action": {"const": action},
                "winner": {"enum": list(_FLAG_TRIAGE_WINNER_CHOICES)},
            },
            "additionalProperties": False,
        }
    if action == FLAG_TRIAGE_EXTEND_OPTION_ID:
        # The extend command echoes back the thresholds it validated, so the
        # host effect resolves the values a reviewer actually chose rather
        # than re-parsing free text.
        return {
            "type": "object",
            "required": ["action", "remove_by_date", "remove_by_release"],
            "properties": {
                "action": {"const": action},
                "remove_by_date": {"type": "string", "minLength": 1},
                "remove_by_release": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": action}},
        "additionalProperties": False,
    }


def flag_triage_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the FlagTriage adapter.

    The wrapper imports from :mod:`sase.bead.flag_gate` because the script text
    is persisted into every gate bundle and revalidated byte for byte; the
    facade keeps that path stable no matter where the entrypoint lives.
    """
    return (
        f"#!{sys.executable}\n"
        "from sase.bead.flag_gate import execute_flag_triage_gate_command\n"
        f"raise SystemExit(execute_flag_triage_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_flag_triage_gate_command(option_id: str) -> int:
    """Validate command input and emit one typed side-effect-free result."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("flag triage command input must be an object", file=sys.stderr)
        return 2
    if option_id not in FLAG_TRIAGE_OPTION_IDS:
        print(f"unsupported flag triage option: {option_id}", file=sys.stderr)
        return 2
    if option_id == FLAG_TRIAGE_REMOVE_OPTION_ID:
        winner = raw_input.get(_FLAG_TRIAGE_WINNER_FIELD_ID)
        if winner not in _FLAG_TRIAGE_WINNER_CHOICES:
            print(
                f"{_FLAG_TRIAGE_WINNER_FIELD_ID} must be one of "
                f"{', '.join(_FLAG_TRIAGE_WINNER_CHOICES)}",
                file=sys.stderr,
            )
            return 2
        print(json.dumps({"action": option_id, "winner": winner}, sort_keys=True))
        return 0
    if option_id == FLAG_TRIAGE_EXTEND_OPTION_ID:
        try:
            remove_by_date, remove_by_release = resolve_flag_triage_extend(raw_input)
        except (SnoozeTimeError, ValueError) as exc:
            # Failing here leaves the gate pending, so a mistyped threshold
            # costs a retry rather than the flag's triage gate.
            print(str(exc), file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "action": option_id,
                    "remove_by_date": remove_by_date,
                    "remove_by_release": remove_by_release,
                },
                sort_keys=True,
            )
        )
        return 0
    if raw_input:
        print("flag triage command input must be empty", file=sys.stderr)
        return 2
    print(json.dumps({"action": option_id}, sort_keys=True))
    return 0
