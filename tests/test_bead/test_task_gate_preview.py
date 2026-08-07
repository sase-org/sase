"""TaskTriage preview and presentation-note rendering contracts."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sase.bead.model import CloseRecord, ReopenCause, TaskPlusOneEvidence
from sase.bead.task_gate import (
    render_task_triage_preview,
    task_triage_presentation_note,
)


def test_task_triage_close_history_placeholders_for_missing_fields() -> None:
    record = CloseRecord(
        closed_at="2026-06-01T00:00:00Z",
        reopened_at="2026-06-15T00:00:00Z",
        reopened_via=ReopenCause.UPDATE,
    )

    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="",
        notes="",
        close_history=(record,),
    )

    assert (
        "> [!WARNING] **↺ Previously closed 2026-06-01T00:00:00Z as "
        "(unrecorded)** (none)"
    ) in preview
    assert "Reopened 2026-06-15T00:00:00Z by a status update." in preview


def test_task_triage_presentation_note_includes_reopen_badge() -> None:
    note = task_triage_presentation_note(
        "sase-task.1", "Flaky retry test in CI", 1, reopen_count=2
    )

    assert note == "sase-task.1 [+1] [↺2] — Flaky retry test in CI"


def test_task_triage_created_rendering_is_absolute_and_clock_independent() -> None:
    """The persisted preview and note must not drift as the gate ages."""

    def render(now: datetime) -> tuple[str, str]:
        with patch("sase.core.time.local_now", return_value=now):
            return (
                render_task_triage_preview(
                    bead_id="sase-task.1",
                    title="Follow up on the cache",
                    description="Make invalidation deterministic.",
                    notes="",
                    created_by="claude_coder",
                    created_at="2026-01-01T00:00:00Z",
                ),
                task_triage_presentation_note(
                    "sase-task.1",
                    "Follow up on the cache",
                    0,
                    created_at="2026-01-01T00:00:00Z",
                ),
            )

    tz = ZoneInfo("America/New_York")
    early = render(datetime(2026, 1, 1, 12, 0, tzinfo=tz))
    late = render(datetime(2027, 9, 9, 12, 0, tzinfo=tz))

    assert early == late
    preview, note = early
    assert "**Created:** 2025-12-31 19:00:00 EST\n" in preview
    assert note == "sase-task.1 — Follow up on the cache · ⧖ 2025-12-31"


def test_task_triage_created_rendering_is_omitted_without_a_timestamp() -> None:
    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="",
        notes="",
    )

    assert "Created" not in preview
    assert (
        task_triage_presentation_note("sase-task.1", "Follow up on the cache", 0)
        == "sase-task.1 — Follow up on the cache"
    )


def test_task_triage_preview_omits_blank_notes_section() -> None:
    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
    )

    assert "## Notes" not in preview
    assert "_No notes._" not in preview
    assert preview.endswith("## Description\n\nMake invalidation deterministic.\n")


def test_task_triage_preview_treats_whitespace_only_notes_as_blank() -> None:
    blank = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
    )
    whitespace_only = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="   \n  ",
    )

    assert whitespace_only == blank


def test_task_triage_preview_renders_notes_section_when_notes_present() -> None:
    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
    )

    assert preview == (
        "# sase-task.1 — Follow up on the cache\n\n"
        "## Description\n\nMake invalidation deterministic.\n\n"
        "## Notes\n\nDiscovered while landing sase-bg.\n"
    )


def test_task_triage_preview_blank_notes_with_evidence_keeps_one_blank_line() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Reproduced after clearing the cache.",
    )

    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
        plus_one_evidence=(evidence,),
    )

    assert "\n\n\n" not in preview
    assert (
        "## Description\n\nMake invalidation deterministic.\n\n## +1 Evidence\n"
        in preview
    )
