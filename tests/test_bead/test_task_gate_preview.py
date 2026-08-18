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
from sase.task_type_gate_presentation import resolve_task_type_gate_display


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


def test_task_triage_presentation_note_includes_post_close_badge() -> None:
    note = task_triage_presentation_note(
        "sase-task.1",
        "Flaky retry test in CI",
        1,
        post_close_count=1,
    )

    assert note == "sase-task.1 [+1] [+1 after close] — Flaky retry test in CI"


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


def test_task_triage_preview_marks_post_close_evidence() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Saw this before the close landed.",
        observed_since="2026-01-01T00:00:00Z",
    )

    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
        plus_one_evidence=(evidence,),
        closed_at="2026-08-01T14:00:00Z",
    )

    assert "**+1 agent.beta · 2026-08-01T15:00:00Z post-close evidence**" in preview
    assert "> **Observed since:** 2026-01-01T00:00:00Z" in preview


def test_task_triage_preview_puts_task_type_fact_in_metadata() -> None:
    display = resolve_task_type_gate_display(
        "flake",
        {"node_id": "tests/x.py::test_y", "evidence": "3/50 under -n 8"},
    )
    assert display is not None

    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        size="medium",
        refs=("research:202608/cache.md",),
        task_type="flake",
        task_type_fields={
            "node_id": "tests/x.py::test_y",
            "evidence": "3/50 under -n 8",
        },
        task_type_display=display,
    )

    size_index = preview.index("**Size:** `medium`")
    refs_index = preview.index("**References:**")
    type_index = preview.index("**Task type:** ≈ `flake`")
    description_index = preview.index("## Description")
    notes_index = preview.index("## Notes")
    assert size_index < refs_index < type_index < description_index < notes_index
    assert "## Flake report" in preview


def test_task_triage_preview_omits_type_fact_without_frozen_display() -> None:
    preview = render_task_triage_preview(
        bead_id="sase-task.1",
        title="Follow up on the cache",
        description="Make invalidation deterministic.",
        notes="",
        task_type="flake",
        task_type_fields={"node_id": "tests/x.py::test_y"},
    )

    assert "**Task type:**" not in preview
    assert preview.index("## Description") < preview.index("## Flake report")
