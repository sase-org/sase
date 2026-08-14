"""Presentation tests for the SASE CONTEXT prompt-panel section."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from tests.ace.tui.widgets._agent_context_helpers import (
    bead_section,
    memory_event,
    pin_context_timezone,
    plan_section,
    skill_event,
    span_style_for,
    workspace_event,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    pin_context_timezone(monkeypatch)


def test_lane_subheaders_use_distinct_accent_colors() -> None:
    text = Text()
    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
        artifact_file_paths=[ArtifactFilePath("result.txt", "/tmp/result.txt")],
    )

    bead_style = span_style_for(text, "▸ BEAD").lower()
    plan_style = span_style_for(text, "▸ PLAN").lower()
    memory_style = span_style_for(text, "▸ MEMORY").lower()
    skills_style = span_style_for(text, "▸ SKILLS").lower()
    workspaces_style = span_style_for(text, "▸ WORKSPACES").lower()
    artifacts_style = span_style_for(text, "▸ ARTIFACTS").lower()
    assert bead_style == "bold #ffaf00"
    assert plan_style == "bold #af87ff"
    assert memory_style == "bold #5fd7ff"
    assert skills_style == "bold #5fd75f"
    assert workspaces_style == "bold #ff87d7"
    assert artifacts_style == "bold #5f87ff"
    assert (
        len(
            {
                plan_style,
                bead_style,
                memory_style,
                skills_style,
                workspaces_style,
                artifacts_style,
            }
        )
        == 6
    )


def test_context_lane_header_details_share_the_summary_style() -> None:
    text = Text()
    append_agent_context_section(
        text,
        bead_section=bead_section(),
        plan_section=plan_section(),
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
        artifact_file_paths=[ArtifactFilePath("result.txt", "/tmp/result.txt")],
    )

    for details in (
        "phase",
        "tale",
        "1 read · 1 file",
        "1 use · 1 skill",
        "1 open · 1 repo",
        "1 artifact",
    ):
        assert span_style_for(text, details) == _agent_context_common.COLOR_SUMMARY


def test_context_rows_share_columns() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
    )

    lines = text.plain.splitlines()
    memory_row = next(line for line in lines if "◇ generated_skills.md" in line)
    skill_row = next(line for line in lines if "◆ sase_plan" in line)
    workspace_row = next(line for line in lines if "▣ sase-core" in line)
    memory_reason = next(
        line for line in lines if "needed generated skill rules" in line
    )
    skill_reason = next(
        line for line in lines if "needed an implementation plan" in line
    )
    workspace_reason = next(
        line for line in lines if "needed to inspect core boundary" in line
    )

    assert memory_row.index("◇") == skill_row.index("◆")
    assert memory_row.index("◇") == workspace_row.index("▣")
    assert memory_row.index("generated_skills.md") == skill_row.index("sase_plan")
    assert memory_row.index("generated_skills.md") == workspace_row.index("sase-core")
    assert memory_reason.index("↳") == skill_reason.index("↳")
    assert memory_reason.index("↳") == workspace_reason.index("↳")
    assert memory_reason.index("↳") == memory_row.index("generated_skills.md")


def test_context_hints_apply_only_to_memory_rows() -> None:
    text = Text()
    hint_state = HeaderHintState(
        hint_counter=8,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )

    append_agent_context_section(
        text,
        memory_reads=(memory_event(),),
        skill_uses=(skill_event(),),
        opened_workspaces=(workspace_event(),),
        hint_state=hint_state,
    )

    assert "◇ [8] generated_skills.md" in text.plain
    assert "◆ sase_plan" in text.plain
    assert "▣ sase-core" in text.plain
    assert "[9]" not in text.plain
    assert hint_state.hint_mappings == {8: "/tmp/test/memory/generated_skills.md"}
    assert hint_state.hint_counter == 9
