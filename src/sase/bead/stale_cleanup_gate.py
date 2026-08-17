"""Trusted notification-gate contract for stale task-bead cleanup.

This module is the contract's front door — every consumer imports the gate's
constants, renderers, and translators from here, and the option command
wrapper persisted into each bundle names this module by path. The
implementation lives in focused siblings:

- :mod:`sase.bead._stale_cleanup_gate_spec` — constants, request spec, command
- :mod:`sase.bead._stale_cleanup_gate_preview` — the Markdown and notification text
- :mod:`sase.bead._stale_cleanup_gate_response` — persisted response → trusted decision

Host effects live in the later actions phase; this facade does not apply them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.bead._stale_cleanup_gate_preview import (
    bead_stale_cleanup_presentation_note,
    render_bead_stale_cleanup_preview,
)
from sase.bead._stale_cleanup_gate_response import (
    BeadStaleCleanupResponse,
    translate_bead_stale_cleanup_response,
)
from sase.bead._stale_cleanup_gate_spec import (
    BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,
    BEAD_STALE_CLEANUP_CLOSE_REASON,
    BEAD_STALE_CLEANUP_COMMAND_PATHS,
    BEAD_STALE_CLEANUP_CONTINUATION_MODE,
    BEAD_STALE_CLEANUP_KIND,
    BEAD_STALE_CLEANUP_MAX_BEADS,
    BEAD_STALE_CLEANUP_OPTION_IDS,
    BEAD_STALE_CLEANUP_PREVIEW_PATH,
    BEAD_STALE_CLEANUP_PRIMARY_BRANCH,
    BEAD_STALE_CLEANUP_QUERY,
    BeadStaleCleanupAction,
    bead_stale_cleanup_gate_command_script,
    bead_stale_cleanup_option_spec,
    bead_stale_cleanup_selection_inputs,
    build_bead_stale_cleanup_gate_spec,
    execute_bead_stale_cleanup_gate_command,
)


def create_bead_stale_cleanup_gate(
    *,
    request_id: str,
    beads: Sequence[Any],
    omitted_count: int = 0,
    min_plus_ones: int,
    stale_after_days: int,
    stale_cleanup_min_beads: int,
    stale_as_of: str,
    producer: Mapping[str, Any] | None = None,
) -> Any:
    """Create one human-only stale-cleanup gate for the offered roster."""
    from sase.notification_gates.service import create_gate

    return create_gate(
        build_bead_stale_cleanup_gate_spec(
            request_id=request_id,
            beads=beads,
            omitted_count=omitted_count,
            min_plus_ones=min_plus_ones,
            stale_after_days=stale_after_days,
            stale_cleanup_min_beads=stale_cleanup_min_beads,
            stale_as_of=stale_as_of,
            producer=producer,
        )
    )


__all__ = [
    "BEAD_STALE_CLEANUP_CLOSE_OPTION_ID",
    "BEAD_STALE_CLEANUP_CLOSE_REASON",
    "BEAD_STALE_CLEANUP_COMMAND_PATHS",
    "BEAD_STALE_CLEANUP_CONTINUATION_MODE",
    "BEAD_STALE_CLEANUP_KIND",
    "BEAD_STALE_CLEANUP_MAX_BEADS",
    "BEAD_STALE_CLEANUP_OPTION_IDS",
    "BEAD_STALE_CLEANUP_PREVIEW_PATH",
    "BEAD_STALE_CLEANUP_PRIMARY_BRANCH",
    "BEAD_STALE_CLEANUP_QUERY",
    "BeadStaleCleanupAction",
    "BeadStaleCleanupResponse",
    "bead_stale_cleanup_gate_command_script",
    "bead_stale_cleanup_option_spec",
    "bead_stale_cleanup_presentation_note",
    "bead_stale_cleanup_selection_inputs",
    "build_bead_stale_cleanup_gate_spec",
    "create_bead_stale_cleanup_gate",
    "execute_bead_stale_cleanup_gate_command",
    "render_bead_stale_cleanup_preview",
    "translate_bead_stale_cleanup_response",
]
