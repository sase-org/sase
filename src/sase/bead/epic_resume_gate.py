"""Trusted notification-gate contract for resuming a stalled epic.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and host effects from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.bead._epic_resume_gate_spec` — constants, request spec, command
- :mod:`sase.bead._epic_resume_gate_preview` — the Markdown and notification text
- :mod:`sase.bead._epic_resume_gate_response` — persisted response → trusted decision
- :mod:`sase.bead._epic_resume_gate_actions` — the host effect a decision authorizes
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead._epic_resume_gate_actions import cancel_epic_resume, resume_stalled_epic
from sase.bead._epic_resume_gate_preview import (
    epic_resume_presentation_note,
    epic_resume_presentation_title,
    render_epic_resume_preview,
)
from sase.bead._epic_resume_gate_response import (
    EpicResumeResponse,
    translate_epic_resume_response,
)
from sase.bead._epic_resume_gate_spec import (
    EPIC_RESUME_COMMAND_PATHS,
    EPIC_RESUME_CONTINUATION_MODE,
    EPIC_RESUME_KIND,
    EPIC_RESUME_OPTION_IDS,
    EPIC_RESUME_PREVIEW_PATH,
    EPIC_RESUME_PRIMARY_BRANCH,
    EPIC_RESUME_QUERY,
    EPIC_RESUME_RESUME_OPTION_ID,
    EpicResumeAction,
    build_epic_resume_gate_spec,
    epic_resume_gate_command_script,
    epic_resume_option_spec,
    execute_epic_resume_gate_command,
)


def create_epic_resume_gate(
    *,
    request_id: str,
    project: str,
    epic_id: str,
    epic_title: str,
    clan_generation: int | str,
    failed_members: Sequence[Any],
    waiting_members: Sequence[Any] = (),
    remaining_phase_count: int,
    stalled_since: str,
    producer: Mapping[str, Any] | None = None,
) -> Any:
    """Create one human-only resume gate for a stalled epic."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_epic_resume_gate_spec(
            request_id=request_id,
            project=project,
            epic_id=epic_id,
            epic_title=epic_title,
            clan_generation=clan_generation,
            failed_members=failed_members,
            waiting_members=waiting_members,
            remaining_phase_count=remaining_phase_count,
            stalled_since=stalled_since,
            producer=producer,
        )
    )


__all__ = [
    "EPIC_RESUME_COMMAND_PATHS",
    "EPIC_RESUME_CONTINUATION_MODE",
    "EPIC_RESUME_KIND",
    "EPIC_RESUME_OPTION_IDS",
    "EPIC_RESUME_PREVIEW_PATH",
    "EPIC_RESUME_PRIMARY_BRANCH",
    "EPIC_RESUME_QUERY",
    "EPIC_RESUME_RESUME_OPTION_ID",
    "EpicResumeAction",
    "EpicResumeResponse",
    "build_epic_resume_gate_spec",
    "cancel_epic_resume",
    "create_epic_resume_gate",
    "epic_resume_gate_command_script",
    "epic_resume_option_spec",
    "epic_resume_presentation_note",
    "epic_resume_presentation_title",
    "execute_epic_resume_gate_command",
    "render_epic_resume_preview",
    "resume_stalled_epic",
    "translate_epic_resume_response",
]
