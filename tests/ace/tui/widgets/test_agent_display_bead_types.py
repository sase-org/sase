"""Agents-tab BEAD lane tests for task and flag bead identities."""

from __future__ import annotations

from sase.ace.tui.models.agent_associated_plan import BeadSummary
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from sase.bead.model import TaskPlusOneEvidence
from tests.ace.tui.widgets._agent_display_bead_section_helpers import (
    CREATED_AT,
    CREATED_LABEL,
    bead_header,
    bead_summary,
    pin_bead_created_clock,  # noqa: F401 (registers the autouse fixture)
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import assert_span_covers


def test_task_and_phase_notes_follow_description() -> None:
    notes = "[2026-08-01T14:09:00Z · bryan] ready for implementation"
    phase = bead_header(bead_summary(notes=notes))
    phase_plain = phase.plain

    assert (
        phase_plain.index("Description:")
        < phase_plain.index("Notes:")
        < phase_plain.index("Size:")
        < phase_plain.index("Created:")
    )

    task_summary = BeadSummary(
        id="sase-task.4",
        phase_title="Task lane",
        description="Show only task-owned metadata.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        created_at=CREATED_AT,
        bead_type="task",
        notes=notes,
    )
    task_header, _ = build_header_text(
        make_agent(agent_name=task_summary.id),
        summary=DetailHeaderSummary(phase_bead=task_summary),
    )
    task_plain = task_header.plain

    assert (
        task_plain.index("Description:")
        < task_plain.index("Notes:")
        < task_plain.index("Size:")
        < task_plain.index("Created:")
    )
    assert "Task Title:" in task_plain
    assert "Epic Plan:" not in task_plain


def test_task_bead_lane_shows_task_type_between_size_and_plus_one() -> None:
    typed_summary = BeadSummary(
        id="sase-task.6",
        phase_title="Flaky retry test",
        description="Reproduce the intermittent failure.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        created_at=CREATED_AT,
        bead_type="task",
        task_type="flake",
    )
    header, _ = build_header_text(
        make_agent(agent_name=typed_summary.id),
        summary=DetailHeaderSummary(phase_bead=typed_summary),
    )
    plain = header.plain

    assert "Task Type:  ≈ flake" in plain
    assert plain.index("Size:") < plain.index("Task Type:") < plain.index("Created:")

    untyped_summary = BeadSummary(
        id="sase-task.7",
        phase_title="Legacy task",
        description="No declared task type.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size=None,
        created_at=CREATED_AT,
        bead_type="task",
    )
    untyped_header, _ = build_header_text(
        make_agent(agent_name=untyped_summary.id),
        summary=DetailHeaderSummary(phase_bead=untyped_summary),
    )

    assert "Task Type:  · untyped" in untyped_header.plain


def test_task_bead_lane_renders_plus_one_count_and_evidence() -> None:
    evidence = TaskPlusOneEvidence(
        timestamp="2026-08-01T15:00:00Z",
        reporter="agent.beta",
        note="Independent reproduction.",
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
        plus_one_evidence=(evidence,),
    )

    header, _ = build_header_text(
        make_agent(agent_name=task_summary.id),
        summary=DetailHeaderSummary(phase_bead=task_summary),
        lane_fold_level=FoldLevel.EXPANDED,
    )

    assert "[+1]" in header.plain
    assert "+1 Reports:" in header.plain
    assert "1 +1 report" in header.plain
    assert "+1 Evidence:" in header.plain
    assert "+1 agent.beta · 2026-08-01T15:00:00Z" in header.plain
    assert "research:202608/cache.md" in header.plain
    assert header.plain.index("+1 Evidence:") < header.plain.index("Created:")


def test_task_bead_lane_uses_type_identity_without_epic_fields() -> None:
    summary = BeadSummary(
        id="sase-task.4",
        phase_title="Task lane",
        description="Show only task-owned metadata.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        created_at=CREATED_AT,
        bead_type="task",
    )
    header, _ = build_header_text(
        make_agent(agent_name=summary.id),
        summary=DetailHeaderSummary(phase_bead=summary),
    )

    assert "▸ BEAD · ◆ task sase-task.4\n" in header.plain
    assert "Task Title: Task lane\n" in header.plain
    assert "Description: Show only task-owned metadata.\n" in header.plain
    assert "Size:  medium " in header.plain
    assert f"Created: {CREATED_LABEL}\n" in header.plain
    assert "Phase Title:" not in header.plain
    assert "Epic Plan:" not in header.plain
    assert "Epic Title:" not in header.plain
    assert_span_covers(header, "◆", "bold #D787FF")


def test_flag_bead_lane_renders_flag_identity_and_thresholds() -> None:
    summary = BeadSummary(
        id="sase-flag",
        phase_title="Remove plugin switch",
        description="Delete the temporary plugin gate.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size=None,
        created_at=CREATED_AT,
        bead_type="flag",
        flag_key="plugins_enabled",
        flag_remove_by_date="2026-12-01",
        flag_remove_by_release="0.19.0",
    )

    header, _ = build_header_text(
        make_agent(agent_name=summary.id),
        summary=DetailHeaderSummary(phase_bead=summary),
    )

    assert "▸ BEAD · ⚑ flag sase-flag\n" in header.plain
    assert "Flag Title: Remove plugin switch\n" in header.plain
    assert "Description: Delete the temporary plugin gate.\n" in header.plain
    assert "Flag Key: ⚑ plugins_enabled\n" in header.plain
    assert "Remove By: 2026-12-01 · v0.19.0\n" in header.plain
    assert f"Created: {CREATED_LABEL}\n" in header.plain
    assert "Size:" not in header.plain
    assert "Epic Plan:" not in header.plain
    assert_span_covers(header, "⚑", "bold #FF875F")
    assert_span_covers(header, "plugins_enabled", "bold #FF875F")
