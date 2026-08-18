"""Agents-tab BEAD lane digest folding and fold-scale tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_associated_plan import BeadSummary
from sase.ace.tui.models.fold_scale import AGENT_FOLD_SCALE, FAMILY_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import (
    BEAD_SECTION_ID,
    bead_detail_level,
    bead_summary_has_foldable_rows,
)
from sase.bead.model import TaskPlusOneEvidence
from tests.ace.tui.widgets._agent_display_bead_section_helpers import (
    CREATED_AT,
    bead_field_labels,
    bead_header,
    bead_summary,
    family_container_agent,
    pin_bead_created_clock,  # noqa: F401 (registers the autouse fixture)
)


def test_bead_detail_level_uses_fold_scale_position() -> None:
    assert bead_detail_level(FoldLevel.COLLAPSED, AGENT_FOLD_SCALE).name == "DIGEST"
    assert bead_detail_level(FoldLevel.EXPANDED, AGENT_FOLD_SCALE).name == "FULL"
    assert bead_detail_level(FoldLevel.EXPANDED, FAMILY_FOLD_SCALE).name == "DIGEST"
    assert bead_detail_level(FoldLevel.FULLY_EXPANDED, FAMILY_FOLD_SCALE).name == "FULL"


def test_bead_digest_folds_only_multiline_log_rows_and_keeps_row_order() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Independent reproduction.\nSecond evidence line.",
        refs=("research:202608/cache.md",),
    )
    task_summary = BeadSummary(
        id="sase-task.5",
        phase_title="Corroborated task",
        description="Carry evidence into the Agents tab.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        created_at=CREATED_AT,
        bead_type="task",
        notes="first note line\nsecond note line\n\nthird note line",
        plus_one_evidence=(evidence,),
    )

    collapsed = bead_header(task_summary)
    expanded = bead_header(task_summary, lane_fold_level=FoldLevel.EXPANDED)

    assert bead_field_labels(collapsed) == bead_field_labels(expanded)
    assert "Task Title:" in collapsed.plain
    assert "Description:" in collapsed.plain
    assert "Notes: ▸ 4 lines (zz to show)" in collapsed.plain
    assert "Size:" in collapsed.plain
    assert "+1 Reports:" in collapsed.plain
    assert "+1 Evidence: ▸ 4 lines (zz to show)" in collapsed.plain
    assert "Created:" in collapsed.plain
    assert "second note line" not in collapsed.plain
    assert "Independent reproduction." not in collapsed.plain
    assert "…" not in collapsed.plain
    assert "second note line" in expanded.plain
    assert "Independent reproduction." in expanded.plain


def test_bead_digest_leaves_single_authored_note_line_inline() -> None:
    notes = "single authored note line that may still wrap in a narrow panel"
    header = bead_header(bead_summary(notes=notes))

    assert f"Notes: {notes}\n" in header.plain
    assert "zz to show" not in header.plain


def test_bead_summary_foldable_predicate_matches_log_rows() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Independent reproduction.",
    )
    task_summary = BeadSummary(
        id="sase-task.5",
        phase_title="Corroborated task",
        description="Carry evidence into the Agents tab.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        created_at=CREATED_AT,
        bead_type="task",
        plus_one_evidence=(evidence,),
    )

    assert not bead_summary_has_foldable_rows(bead_summary(notes=None))
    assert not bead_summary_has_foldable_rows(bead_summary(notes="one line"))
    assert bead_summary_has_foldable_rows(bead_summary(notes="one\ntwo"))
    assert bead_summary_has_foldable_rows(task_summary)


def test_family_bead_section_override_expands_folded_logs() -> None:
    notes = "first family note\nsecond family note"
    agent = family_container_agent()

    folded = bead_header(
        bead_summary(notes=notes),
        agent=agent,
        lane_fold_level=FoldLevel.EXPANDED,
    )
    expanded = bead_header(
        bead_summary(notes=notes),
        agent=agent,
        lane_fold_level=FoldLevel.EXPANDED,
        lane_section_fold_overrides={BEAD_SECTION_ID: FoldLevel.FULLY_EXPANDED},
    )

    assert "Notes: ▸ 2 lines (zz to show)" in folded.plain
    assert "second family note" not in folded.plain
    assert notes in expanded.plain
    assert "Notes: ▸" not in expanded.plain
