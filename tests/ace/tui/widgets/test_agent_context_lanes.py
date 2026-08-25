"""Lane-content tests for the SASE CONTEXT prompt-panel section."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.patch.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import BEAD_SECTION_ID
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_ARTIFACT_FILE_BASENAME,
    COLOR_ARTIFACTS_SUBHEADER,
    COLOR_SUMMARY,
    count_phrase,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from tests.ace.tui.widgets._agent_context_helpers import (
    bead_section,
    fold_only_section_marker_ids,
    memory_event,
    pin_context_timezone,
    plan_section,
    section_marker_ids,
    skill_event,
    span_style_for,
    task_bead_section,
    workspace_event,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_context_timezone(monkeypatch)


def test_empty_context_appends_nothing() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=())
    assert text.plain == ""


def test_plan_only_context_renders_plan_lane_and_returns_its_range() -> None:
    text = Text()
    section = plan_section()

    plan_range = append_agent_context_section(text, plan_section=section)

    assert plan_range is not None
    plan_start, plan_end = plan_range
    assert text[plan_start:plan_end].plain == section.logical_text.plain
    assert "SASE CONTEXT\n" in text.plain
    assert "▸ PLAN · tale\n" in text.plain
    assert "  Title: Plan lane\n" in text.plain
    assert "   Size:  medium " in text.plain
    assert "▸ MEMORY" not in text.plain
    assert "▸ SKILLS" not in text.plain
    assert "▸ WORKSPACES" not in text.plain


def test_bead_only_context_creates_context_and_has_no_plan_range() -> None:
    text = Text()

    plan_range = append_agent_context_section(text, bead_section=bead_section())

    assert plan_range is None
    assert "SASE CONTEXT\n" in text.plain
    assert "▸ BEAD · ↳ phase sase-42.3\n" in text.plain
    assert "ID:" not in text.plain
    assert text.plain.count("sase-42.3") == 1
    assert "  Phase Title: Selected phase metadata\n" in text.plain
    assert " Description: Render only the selected phase metadata.\n" in text.plain
    assert "        Size:  medium \n" in text.plain
    assert "   Epic Plan: sase/repos/plans/epic.md\n" in text.plain
    assert "  Epic Title: Phase-local context lane\n" in text.plain
    assert "Created: 2026-08-01 10:30:00 EDT" in text.plain
    assert "▸ PLAN" not in text.plain
    assert_logical_section_is_compact(text, "SASE CONTEXT", "▸ BEAD")
    assert_rendered_section_is_compact(text, "SASE CONTEXT", "▸ BEAD")


def test_plan_precedes_bead_without_changing_plan_range_bookkeeping() -> None:
    text = Text()
    bead = bead_section()
    plan = plan_section()
    responsive_ranges: dict[str, tuple[int, int]] = {}

    plan_range = append_agent_context_section(
        text,
        bead_section=bead,
        plan_section=plan,
        responsive_ranges=responsive_ranges,
    )

    assert plan_range == responsive_ranges["PLAN"]
    bead_start, bead_end = responsive_ranges["BEAD"]
    plan_start, plan_end = responsive_ranges["PLAN"]
    assert text[bead_start:bead_end].plain == bead.logical_text.plain
    assert text[plan_start:plan_end].plain == plan.logical_text.plain
    assert plan_end < bead_start


def test_task_authored_plan_context_renders_plan_then_bead_lane() -> None:
    text = Text()

    append_agent_context_section(
        text,
        bead_section=task_bead_section(),
        plan_section=plan_section(),
    )

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ BEAD · ◆ task sase-task\n" in plain
    assert "  Task Title: Task authored a plan\n" in plain
    assert "▸ PLAN · tale\n" in plain
    assert "   Size:  medium " in plain
    assert plain.index("▸ PLAN") < plain.index("▸ BEAD")


def test_memory_only_context_omits_empty_skills_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(memory_event(),), skill_uses=())

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "generated_skills.md" in plain
    assert "▸ SKILLS" not in plain
    assert "▸ WORKSPACES" not in plain
    assert "▸ PLAN" not in plain
    assert "none recorded" not in plain
    assert_logical_section_is_compact(text, "SASE CONTEXT", "▸ MEMORY")
    assert_rendered_section_is_compact(text, "SASE CONTEXT", "▸ MEMORY")


def test_skills_only_context_omits_empty_memory_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=(skill_event(),))

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ SKILLS · 1 use · 1 skill\n" in plain
    assert "sase_plan" in plain
    assert "▸ PLAN" not in plain
    assert "▸ MEMORY" not in plain
    assert "▸ WORKSPACES" not in plain
    assert "none recorded" not in plain


def test_workspaces_only_context_omits_empty_other_lanes() -> None:
    text = Text()
    append_agent_context_section(
        text,
        opened_workspaces=(workspace_event(),),
    )

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ WORKSPACES · 1 open · 1 repo\n" in plain
    assert "▣ sase-core" in plain
    assert "→ /tmp/workspaces/sase-core_13" in plain
    assert "↳ needed to inspect core boundary" in plain
    assert "▸ MEMORY" not in plain
    assert "▸ SKILLS" not in plain
    assert "▸ PLAN" not in plain
    assert "none recorded" not in plain


def test_artifacts_lane_groups_output_fields_and_counts() -> None:
    text = Text()
    agent = make_agent(
        step_output={
            "meta_commits": [
                {
                    "message": "feat: grouped outputs",
                    "sha": "abcdef1234567890",
                }
            ]
        }
    )

    append_agent_context_section(
        text,
        agent=agent,
        delta_entries=[
            DeltaEntry(
                path="src/output.py",
                change_type="M",
                line_stats=DeltaLineStats(modified=2),
            )
        ],
        artifact_file_paths=[
            ArtifactFilePath("reports/result.md", "/tmp/reports/result.md"),
        ],
    )

    plain = text.plain
    assert "▸ ARTIFACTS · 1 commit · 1 file · 1 artifact file\n" in plain
    assert "  Commits:\n    ▣ test\n" in plain
    assert "      abcdef123456 feat: grouped outputs\n" in plain
    assert "  Deltas:\n    ~ src/output.py  ~2\n" in plain
    assert "  Files:\n    • reports/result.md\n" in plain
    assert section_marker_ids(text) == ["sase-context"]


def test_family_context_marks_heading_title_and_lanes_fold_only() -> None:
    text = Text()

    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        fold_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )

    assert "SASE CONTEXT · 2\n" in text.plain
    ids = section_marker_ids(text)
    assert ids[0] == "sase-context"
    assert set(ids[1:]) == {"plan", BEAD_SECTION_ID}
    assert fold_only_section_marker_ids(text) == ids[1:]
    assert "sase-context" not in fold_only_section_marker_ids(text)


def test_non_family_context_still_marks_only_sase_context() -> None:
    text = Text()

    append_agent_context_section(text, plan_section=plan_section())

    assert section_marker_ids(text) == ["sase-context"]
    assert fold_only_section_marker_ids(text) == []


def test_artifacts_lane_chrome_uses_its_palette_and_shared_path_idiom() -> None:
    text = Text()
    append_agent_context_section(
        text,
        plan_section=plan_section(),
        delta_entries=[DeltaEntry(path="src/output.py", change_type="M")],
        artifact_file_paths=[
            ArtifactFilePath("reports/result.md", "/tmp/reports/result.md"),
        ],
    )

    assert span_style_for(text, "▸ ARTIFACTS") == COLOR_ARTIFACTS_SUBHEADER
    assert span_style_for(text, "  Deltas:") == COLOR_SUMMARY
    assert span_style_for(text, "  Files:") == COLOR_SUMMARY
    assert span_style_for(text, "•") == COLOR_ARTIFACTS_SUBHEADER
    for basename in ("plan.md", "output.py", "result.md"):
        assert span_style_for(text, basename) == COLOR_ARTIFACT_FILE_BASENAME


def test_count_phrase_pluralizes_context_counts() -> None:
    assert count_phrase(1, "read") == "1 read"
    assert count_phrase(2, "read") == "2 reads"
    assert count_phrase(1, "file") == "1 file"
    assert count_phrase(3, "file") == "3 files"
    assert count_phrase(1, "use") == "1 use"
    assert count_phrase(2, "skill") == "2 skills"
    assert count_phrase(1, "open") == "1 open"
    assert count_phrase(2, "repo") == "2 repos"


def test_workspace_lane_overflow_shows_earliest_open() -> None:
    text = Text()
    events = tuple(
        workspace_event(
            name=f"repo-{index}",
            opened_at=f"2026-06-14T14:2{index}:00+00:00",
            reason=f"reason {index}",
        )
        for index in range(6, -1, -1)
    )

    append_agent_context_section(text, opened_workspaces=events)

    plain = text.plain
    assert "▸ WORKSPACES · 7 opens · 7 repos\n" in plain
    assert "repo-6" in plain
    assert "repo-2" in plain
    assert "repo-1" not in plain
    assert "repo-0" not in plain
    assert "+ 2 more · 14:20 earliest\n" in plain
