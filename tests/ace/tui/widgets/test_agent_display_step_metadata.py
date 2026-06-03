"""Tests for agent display workflow variables."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    MAJOR_SECTION_RULE,
    assert_dim_divider_before,
)


class TestWorkflowVariablesHeader:
    def test_header_present_when_meta_fields_exist(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
            }
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES\n" in header.plain
        assert "Commit Message: fix: align\n" in header.plain
        assert "New Commit: 96a895335\n" in header.plain
        assert_dim_divider_before(header, "WORKFLOW VARIABLES\n")
        assert header.plain.count(MAJOR_SECTION_RULE) == 2

    def test_header_absent_when_no_meta_fields(self) -> None:
        agent = make_agent(step_output={"status": "ok"})

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1

    def test_header_absent_when_no_step_output(self) -> None:
        agent = make_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1
