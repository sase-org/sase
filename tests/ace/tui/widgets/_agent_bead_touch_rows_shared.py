"""Shared helpers for the split agent bead-touch row tests.

The tests formerly lived in a single ``test_agent_bead_touch_rows`` module.
Helpers shared by more than one split module live here under public names;
the ``test_agent_bead_touch_rows_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from rich.text import Text

from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.bead_touches import BeadTouchEntry
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_bead_touches import (
    _styled_bead_verb_chips,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    HeaderHintState,
)
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from sase.core.bead_touch_index_facade import BeadNotePreview, BeadTouchClose

__all__ = [
    "bead_chip_names",
    "collapsed_preview_text",
    "contains_folded_text",
    "make_artifact_read_display",
    "make_artifact_read_event",
    "make_bead_touch_close",
    "make_bead_touch_entry",
    "make_header_hint_state",
    "pin_utc_timezone",
    "render_header_lines",
]


def bead_chip_names(entry: BeadTouchEntry) -> list[str]:
    return [chip for chip, _ in _styled_bead_verb_chips(entry)]


def pin_utc_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def make_bead_touch_entry(
    bead_id: str,
    timestamp: str,
    *,
    verbs: dict[str, int] | None = None,
    title: str = "",
    own: bool = False,
    label: str | None = None,
    read_reasons: tuple[str, ...] = (),
    current_note_count: int = 0,
    note_preview: BeadNotePreview | None = None,
    note_label: str | None = None,
    agent_close: BeadTouchClose | None = None,
    creation_reason: str = "",
    creation_reason_truncated: bool = False,
) -> BeadTouchEntry:
    return BeadTouchEntry(
        bead_id=bead_id,
        title=title,
        verbs=dict(verbs or {}),
        first_at=timestamp,
        last_at=timestamp,
        own=own,
        agent_label=label,
        read_reasons=read_reasons,
        current_note_count=current_note_count,
        note_preview=note_preview,
        note_agent_label=note_label,
        agent_close=agent_close,
        creation_reason=creation_reason,
        creation_reason_truncated=creation_reason_truncated,
    )


def make_bead_touch_close(
    timestamp: str,
    *,
    resolution: str = "done",
    reason: str = "",
    standing: bool = True,
) -> BeadTouchClose:
    return BeadTouchClose(
        closed_at=timestamp,
        resolution=resolution,
        reason=reason,
        standing=standing,
    )


def make_artifact_read_event(
    *,
    ref: str,
    timestamp: str,
    read_id: str,
    resolved_path: str | None = "/tmp/test/plan.md",
) -> ArtifactReadEvent:
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=read_id,
        timestamp=timestamp,
        project="test",
        cwd="/tmp/test",
        ref=ref,
        reason="needed it",
        agent_name="alpha",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/tmp/test/artifacts",
        recorded_link=False,
        resolved_path=resolved_path,
    )


def make_artifact_read_display(event: ArtifactReadEvent) -> ArtifactReadDisplayEvent:
    return ArtifactReadDisplayEvent(event=event)


def make_header_hint_state(start: int = 1) -> HeaderHintState:
    return HeaderHintState(
        hint_counter=start,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )


def render_header_lines(header: Text, *, width: int) -> list[str]:
    output = StringIO()
    console = Console(file=output, width=width, color_system=None)
    console.print(header, end="")
    return output.getvalue().splitlines()


def collapsed_preview_text(text: str) -> str:
    return " ".join(text.replace("│", " ").split())


def contains_folded_text(haystack: str, needle: str) -> bool:
    compact = haystack.replace(" ", "").replace("│", "")
    return needle.replace(" ", "") in compact
