"""Trusted notification-gate contract for standalone task-bead triage.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and host effects from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.bead._task_gate_spec` — constants, request spec, option commands
- :mod:`sase.bead._task_gate_preview` — the Markdown and notification text
- :mod:`sase.bead._task_gate_response` — persisted response → trusted decision
- :mod:`sase.bead._task_gate_actions` — the host effects a decision authorizes
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead._task_gate_actions import (
    bead_gate_actor,
    cancel_task_triage,
    close_task_triage,
    launch_task_triage,
    snooze_task_triage,
)
from sase.bead._task_gate_preview import (
    bounded_gate_title,
    render_task_triage_preview,
    task_triage_presentation_note,
)
from sase.bead._task_gate_response import (
    TaskTriageResponse,
    translate_task_triage_response,
    validate_task_triage_feedback,
)
from sase.bead._task_gate_spec import (
    TASK_TRIAGE_CLOSE_OPTION_ID,
    TASK_TRIAGE_COMMAND_PATHS,
    TASK_TRIAGE_CONTINUATION_MODE,
    TASK_TRIAGE_KIND,
    TASK_TRIAGE_LAUNCH_OPTION_ID,
    TASK_TRIAGE_OPTION_FEEDBACK,
    TASK_TRIAGE_OPTION_ICONS,
    TASK_TRIAGE_OPTION_IDS,
    TASK_TRIAGE_OPTION_LABELS,
    TASK_TRIAGE_PREVIEW_PATH,
    TASK_TRIAGE_PRIMARY_BRANCH,
    TASK_TRIAGE_QUERY,
    TASK_TRIAGE_SNOOZE_OPTION_ID,
    TASK_TRIAGE_SNOOZE_REASON,
    TaskTriageAction,
    build_task_triage_gate_spec,
    close_record_payload,
    execute_task_triage_gate_command,
    task_triage_gate_command_script,
    task_triage_result_schema,
)
from sase.bead.model import CloseRecord, TaskPlusOneEvidence


def create_task_triage_gate(
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
) -> Any:
    """Create one human-only triage gate for a ready standalone task bead."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_task_triage_gate_spec(
            request_id=request_id,
            bead_id=bead_id,
            project=project,
            title=title,
            description=description,
            notes=notes,
            created_by=created_by,
            created_at=created_at,
            size=size,
            refs=refs,
            plus_one_evidence=plus_one_evidence,
            close_history=close_history,
            producer=producer,
        )
    )


__all__ = [
    "TASK_TRIAGE_CLOSE_OPTION_ID",
    "TASK_TRIAGE_COMMAND_PATHS",
    "TASK_TRIAGE_CONTINUATION_MODE",
    "TASK_TRIAGE_KIND",
    "TASK_TRIAGE_LAUNCH_OPTION_ID",
    "TASK_TRIAGE_OPTION_FEEDBACK",
    "TASK_TRIAGE_OPTION_ICONS",
    "TASK_TRIAGE_OPTION_IDS",
    "TASK_TRIAGE_OPTION_LABELS",
    "TASK_TRIAGE_PREVIEW_PATH",
    "TASK_TRIAGE_PRIMARY_BRANCH",
    "TASK_TRIAGE_QUERY",
    "TASK_TRIAGE_SNOOZE_OPTION_ID",
    "TASK_TRIAGE_SNOOZE_REASON",
    "TaskTriageAction",
    "TaskTriageResponse",
    "bead_gate_actor",
    "bounded_gate_title",
    "cancel_task_triage",
    "close_record_payload",
    "close_task_triage",
    "create_task_triage_gate",
    "execute_task_triage_gate_command",
    "launch_task_triage",
    "render_task_triage_preview",
    "snooze_task_triage",
    "task_triage_gate_command_script",
    "task_triage_presentation_note",
    "task_triage_result_schema",
    "translate_task_triage_response",
    "validate_task_triage_feedback",
]
