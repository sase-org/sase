"""Trusted notification-gate contract for a due flag bead's removal triage.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and host effects from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.bead._flag_gate_spec` — constants, request spec, option commands
- :mod:`sase.bead._flag_gate_preview` — the Markdown and notification text
- :mod:`sase.bead._flag_gate_response` — persisted response → trusted decision
- :mod:`sase.bead._flag_gate_actions` — the host effects a decision authorizes

A live task bead is either ready or snoozed; a live flag task bead is
either not yet due or ``due`` (see
:func:`sase.bead.flag_due.flag_removal_due`). This gate is raised only for
the latter, and its four options -- Remove, Extend, Keep, and Close -- are
the only honest answers to "this flag's removal is overdue": delete the Off
branch, push both thresholds out, declare the behavior a config field, or
abandon the removal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead._flag_gate_actions import (
    close_flag_triage,
    extend_flag_triage,
    keep_flag_triage,
    remove_flag_triage,
)
from sase.bead._flag_gate_preview import (
    flag_triage_presentation_note,
    render_flag_triage_preview,
)
from sase.bead._flag_gate_response import (
    FlagTriageResponse,
    translate_flag_triage_response,
)
from sase.bead._flag_gate_spec import (
    FLAG_TRIAGE_CLOSE_OPTION_ID,
    FLAG_TRIAGE_COMMAND_PATHS,
    FLAG_TRIAGE_CONTINUATION_MODE,
    FLAG_TRIAGE_EXTEND_OPTION_ID,
    FLAG_TRIAGE_KEEP_OPTION_ID,
    FLAG_TRIAGE_KIND,
    FLAG_TRIAGE_OPTION_FEEDBACK,
    FLAG_TRIAGE_OPTION_ICONS,
    FLAG_TRIAGE_OPTION_IDS,
    FLAG_TRIAGE_OPTION_LABELS,
    FLAG_TRIAGE_PREVIEW_PATH,
    FLAG_TRIAGE_PRIMARY_BRANCH,
    FLAG_TRIAGE_QUERY,
    FLAG_TRIAGE_REMOVE_OPTION_ID,
    FlagTriageAction,
    build_flag_triage_gate_spec,
    execute_flag_triage_gate_command,
    flag_triage_flag_payload,
    flag_triage_gate_command_script,
    flag_triage_option_spec,
    flag_triage_presentation,
    flag_triage_result_schema,
)
from sase.bead.flag_fields import FLAG_TASK_TYPE
from sase.bead.flag_fields import FlagFields


def create_flag_triage_gate(
    *,
    request_id: str,
    bead_id: str,
    project: str,
    title: str,
    flag: FlagFields,
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
) -> Any:
    """Create one human-only removal-triage gate for a due flag bead."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_flag_triage_gate_spec(
            request_id=request_id,
            bead_id=bead_id,
            project=project,
            title=title,
            flag=flag,
            due_state=due_state,
            due_as_of=due_as_of,
            release=release,
            definition=definition,
            description=description,
            notes=notes,
            created_by=created_by,
            created_at=created_at,
            size=size,
            refs=refs,
            kind=kind,
            task_type=task_type,
            task_type_fields=task_type_fields,
            producer=producer,
        )
    )


__all__ = [
    "FLAG_TRIAGE_CLOSE_OPTION_ID",
    "FLAG_TRIAGE_COMMAND_PATHS",
    "FLAG_TRIAGE_CONTINUATION_MODE",
    "FLAG_TRIAGE_EXTEND_OPTION_ID",
    "FLAG_TRIAGE_KEEP_OPTION_ID",
    "FLAG_TRIAGE_KIND",
    "FLAG_TRIAGE_OPTION_FEEDBACK",
    "FLAG_TRIAGE_OPTION_ICONS",
    "FLAG_TRIAGE_OPTION_IDS",
    "FLAG_TRIAGE_OPTION_LABELS",
    "FLAG_TRIAGE_PREVIEW_PATH",
    "FLAG_TRIAGE_PRIMARY_BRANCH",
    "FLAG_TRIAGE_QUERY",
    "FLAG_TRIAGE_REMOVE_OPTION_ID",
    "FlagTriageAction",
    "FlagTriageResponse",
    "build_flag_triage_gate_spec",
    "close_flag_triage",
    "create_flag_triage_gate",
    "execute_flag_triage_gate_command",
    "extend_flag_triage",
    "flag_triage_flag_payload",
    "flag_triage_gate_command_script",
    "flag_triage_option_spec",
    "flag_triage_presentation",
    "flag_triage_presentation_note",
    "flag_triage_result_schema",
    "keep_flag_triage",
    "remove_flag_triage",
    "render_flag_triage_preview",
    "translate_flag_triage_response",
]
