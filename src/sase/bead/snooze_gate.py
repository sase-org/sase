"""Trusted notification-gate contract for a woken snoozed task bead.

The gate a snoozed task bead's wake time raises. It is born already snoozed —
the spec declares ``presentation.snooze_until`` and the gate service creates
its notification muted and snoozed to that instant — so the wake needs no
second timer: the notification snooze machinery resurfaces the row, and the
bead is visible in the panel's Snoozed tab the whole time it sleeps.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and host effects from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.bead._snooze_gate_spec` — constants, request spec, option commands
- :mod:`sase.bead._snooze_gate_preview` — the Markdown and notification text
- :mod:`sase.bead._snooze_gate_response` — persisted response → trusted decision
- :mod:`sase.bead._snooze_gate_actions` — the host effects a decision authorizes

Its shape deliberately mirrors :mod:`sase.bead.task_gate`: same payload
fields, same command wrapper, same preview renderer. Only the decisions
differ, because the question a woken bead asks ("is this still worth doing?")
is not the question a ready one asks ("who works this?").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead._snooze_gate_actions import (
    close_bead_snooze,
    ready_bead_snooze,
    resnooze_bead_snooze,
)
from sase.bead._snooze_gate_preview import (
    bead_snooze_presentation_note,
    render_bead_snooze_preview,
)
from sase.bead._snooze_gate_response import (
    BeadSnoozeResponse,
    translate_bead_snooze_response,
)
from sase.bead._snooze_gate_spec import (
    BEAD_SNOOZE_CLOSE_OPTION_ID,
    BEAD_SNOOZE_COMMAND_PATHS,
    BEAD_SNOOZE_CONTINUATION_MODE,
    BEAD_SNOOZE_KIND,
    BEAD_SNOOZE_OPTION_FEEDBACK,
    BEAD_SNOOZE_OPTION_IDS,
    BEAD_SNOOZE_PREVIEW_PATH,
    BEAD_SNOOZE_PRIMARY_BRANCH,
    BEAD_SNOOZE_QUERY,
    BEAD_SNOOZE_READY_NOTE,
    BEAD_SNOOZE_READY_OPTION_ID,
    BEAD_SNOOZE_SNOOZE_OPTION_ID,
    BeadSnoozeAction,
    bead_snooze_gate_command_script,
    bead_snooze_option_spec,
    bead_snooze_presentation,
    build_bead_snooze_gate_spec,
    execute_bead_snooze_gate_command,
)
from sase.bead.model import CloseRecord, SnoozeRecord, TaskPlusOneEvidence


def create_bead_snooze_gate(
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
) -> Any:
    """Create one human-only wake gate for a snoozed standalone task bead."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_bead_snooze_gate_spec(
            request_id=request_id,
            bead_id=bead_id,
            project=project,
            title=title,
            snooze=snooze,
            description=description,
            notes=notes,
            created_by=created_by,
            created_at=created_at,
            size=size,
            refs=refs,
            plus_one_evidence=plus_one_evidence,
            close_history=close_history,
            task_type=task_type,
            task_type_fields=task_type_fields,
            producer=producer,
        )
    )


__all__ = [
    "BEAD_SNOOZE_CLOSE_OPTION_ID",
    "BEAD_SNOOZE_COMMAND_PATHS",
    "BEAD_SNOOZE_CONTINUATION_MODE",
    "BEAD_SNOOZE_KIND",
    "BEAD_SNOOZE_OPTION_FEEDBACK",
    "BEAD_SNOOZE_OPTION_IDS",
    "BEAD_SNOOZE_PREVIEW_PATH",
    "BEAD_SNOOZE_PRIMARY_BRANCH",
    "BEAD_SNOOZE_QUERY",
    "BEAD_SNOOZE_READY_NOTE",
    "BEAD_SNOOZE_READY_OPTION_ID",
    "BEAD_SNOOZE_SNOOZE_OPTION_ID",
    "BeadSnoozeAction",
    "BeadSnoozeResponse",
    "bead_snooze_gate_command_script",
    "bead_snooze_option_spec",
    "bead_snooze_presentation",
    "bead_snooze_presentation_note",
    "build_bead_snooze_gate_spec",
    "close_bead_snooze",
    "create_bead_snooze_gate",
    "execute_bead_snooze_gate_command",
    "ready_bead_snooze",
    "render_bead_snooze_preview",
    "resnooze_bead_snooze",
    "translate_bead_snooze_response",
]
