"""Shared helpers for the split agent bead-touch tests.

The tests formerly lived in a single ``test_agent_bead_touches`` module.
Helpers needed by more than one split module live here under public names;
the ``test_agent_bead_touches_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from sase.ace.tui._bead_touches_shared import BeadTouchDisplayEvent
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from sase.core.bead_touch_index_facade import (
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
)

__all__ = [
    "make_bead_read",
    "make_bead_touch",
    "make_bead_touch_display",
]


def make_bead_touch(
    actor: str,
    bead_id: str,
    *,
    verbs: dict[str, int] | None = None,
    title: str = "",
    first_at: str = "",
    last_at: str = "",
    current_note_count: int = 0,
    note_preview: BeadNotePreview | None = None,
    close: BeadTouchClose | None = None,
    creation_reason: str = "",
    creation_reason_truncated: bool = False,
) -> BeadTouch:
    return BeadTouch(
        actor=actor,
        bead_id=bead_id,
        title=title,
        verbs=dict(verbs or {}),
        first_at=first_at,
        last_at=last_at,
        current_note_count=current_note_count,
        note_preview=note_preview,
        close=close,
        creation_reason=creation_reason,
        creation_reason_truncated=creation_reason_truncated,
    )


def make_bead_touch_display(
    touch: BeadTouch, label: str | None = None
) -> BeadTouchDisplayEvent:
    return BeadTouchDisplayEvent(touch=touch, agent_label=label)


def make_bead_read(
    ref: str,
    timestamp: str,
    *,
    read_id: str,
    label: str | None = None,
    reason: str = "needed it",
) -> ArtifactReadDisplayEvent:
    return ArtifactReadDisplayEvent(
        event=ArtifactReadEvent(
            schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
            id=read_id,
            timestamp=timestamp,
            project="test",
            cwd="/tmp/test",
            ref=ref,
            reason=reason,
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            recorded_link=False,
            resolved_path=None,
        ),
        agent_label=label,
    )
