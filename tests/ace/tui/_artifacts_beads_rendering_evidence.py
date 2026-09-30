"""Plus-one, notes, and attachment rendering for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from sase.ace.tui.widgets.artifacts.beads_detail import (
    bead_body_markdown,
    bead_properties_header,
)
from sase.ace.tui.widgets.artifacts.beads_list import build_bead_options
from sase.ace.tui.widgets.artifacts.beads_rendering import task_text
from sase.bead.model import (
    BeadNote,
    BeadNoteAttachment,
    CloseRecord,
    ReopenCause,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)
from tests.ace.tui._artifacts_beads_helpers import pinned_clock, snapshot

__all__ = [
    "pinned_clock",
    "test_detail_body_renders_structured_notes_as_markdown_entries",
    "test_detail_note_attachments_render_chips_and_descriptor_strip",
    "test_detail_note_without_attachments_renders_verbatim",
    "test_task_rows_and_detail_render_plus_one_badges_and_evidence",
    "test_task_rows_and_detail_render_post_close_plus_one_badges",
    "test_task_rows_and_detail_render_reopen_badges_and_close_history",
]


def test_task_rows_and_detail_render_plus_one_badges_and_evidence(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Reproduced after clearing the cache.",
            refs=("research:202608/cache.md",),
        )
    )

    options, _rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    task_row = next(
        option.prompt.plain for option in options if option.id == "task:alpha-ready"
    )
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    body = bead_body_markdown(issue)

    assert "[+1]" in task_row
    assert "[+1]" in capture.get()
    assert "+1 reports" in capture.get()
    assert "## +1 Evidence" in body
    assert "+1 agent.beta · 2026-08-01T15:00:00Z" in body
    assert "research:202608/cache.md" in body


def test_detail_body_renders_structured_notes_as_markdown_entries(
    tmp_path: Path,
    pinned_clock: None,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.notes = [
        BeadNote(
            id="note-1",
            timestamp="2026-07-07T12:00:00Z",
            author="agent.alpha",
            text="First note body.",
        ),
        BeadNote(
            id="note-2",
            timestamp="2026-07-08T15:30:00Z",
            author="owner@example.com",
            text="Second note body.",
        ),
    ]

    body = bead_body_markdown(issue)

    assert "## Notes (2)" in body
    assert "### #1 · 2026-07-07 08:00:00 EDT · 1d ago · agent.alpha" in body
    assert "First note body." in body
    assert "### #2 · 2026-07-08 11:30:00 EDT · 30m ago · owner@example.com" in body
    assert "Second note body." in body
    assert "[2026-07-07T12:00:00Z · agent.alpha]" not in body


def test_task_rows_and_detail_render_post_close_plus_one_badges(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.status = Status.CLOSED
    issue.closed_at = "2026-08-01T14:00:00Z"
    issue.resolution = Resolution.DONE
    issue.plus_one_evidence.append(
        TaskPlusOneEvidence(
            timestamp="2026-08-01T15:00:00Z",
            reporter="agent.beta",
            note="Saw this before the close landed.",
            observed_since="2026-01-01T00:00:00Z",
        )
    )

    row = task_text(issue, triage=False, plan_link=False).plain
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    body = bead_body_markdown(issue)

    assert "[+1 after close]" in row
    assert "[+1 after close]" in capture.get()
    assert "Post-close +1" in capture.get()
    assert "post-close evidence" in body
    assert "**Observed since:** 2026-01-01T00:00:00Z" in body


def test_task_rows_and_detail_render_reopen_badges_and_close_history(
    tmp_path: Path,
) -> None:
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.close_history.append(
        CloseRecord(
            closed_at="2026-07-30T09:12:04Z",
            reopened_at="2026-08-05T17:04:11Z",
            reopened_via=ReopenCause.PLUS_ONE,
            close_reason="Not reproducible on main; the retry shim already covers this.",
            resolution=Resolution.CANCELED,
            reopened_by="claude.probe",
        )
    )

    options, _rows = build_bead_options(
        value,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    task_row = next(
        option.prompt.plain for option in options if option.id == "task:alpha-ready"
    )
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(
            bead_properties_header(
                issue,
                value,
                project="alpha",
                project_name="Alpha",
            )
        )
    properties = capture.get()
    body = bead_body_markdown(issue)

    assert "[↺1]" in task_row
    assert "Previously closed" in properties
    assert "↺1" in properties
    assert "## Previously Closed" in body
    assert body.index("## Previously Closed") < body.index("## Description")
    assert "↺ Closed 2026-07-30T09:12:04Z · canceled" in body
    assert "Reopened 2026-08-05T17:04:11Z by a +1 from @claude.probe" in body


def test_detail_note_attachments_render_chips_and_descriptor_strip(
    tmp_path: Path,
    pinned_clock: None,
) -> None:
    """Notes with manifests render chips plus a compact attachments strip."""
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.notes = [
        BeadNote(
            id="note-1",
            timestamp="2026-07-07T12:00:00Z",
            author="agent.alpha",
            text="Crash right after login @attachment:login.png — full log: @attachment:crash.log",
            attachments=(
                BeadNoteAttachment(
                    name="login.png",
                    sha256="9f2c1e0b77aa4c10" + "0" * 48,
                    size_bytes=188416,
                    mime_type="image/png",
                    image=(1280, 720),
                ),
                BeadNoteAttachment(
                    name="crash.log",
                    sha256="41aa07c3e9b1d2f0" + "1" * 48,
                    size_bytes=2202009,
                    mime_type="text/plain",
                ),
            ),
        ),
    ]

    body = bead_body_markdown(issue)

    assert "📎 2" in body
    assert "[login.png]" in body
    assert "[crash.log]" in body
    assert "@attachment:" not in body
    assert "**Attachments:**" in body
    assert "login.png · image/png · 1280×720" in body
    assert "crash.log · text/plain" in body


def test_detail_note_without_attachments_renders_verbatim(
    tmp_path: Path,
    pinned_clock: None,
) -> None:
    """Notes without manifests pay zero attachment cost and render unchanged."""
    value = snapshot(tmp_path)
    issue = value.tasks[0].issue
    issue.notes = [
        BeadNote(
            id="note-1",
            timestamp="2026-07-07T12:00:00Z",
            author="agent.alpha",
            text="Plain note with @large and me@host left alone.",
        ),
    ]

    body = bead_body_markdown(issue)

    assert "Plain note with @large and me@host left alone." in body
    assert "**Attachments:**" not in body
