"""Tests for agent display workflow variables."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    DetailHeaderSummary,
    build_header_text,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import MAJOR_SECTION_RULE


class TestWorkflowVariablesHeader:
    def test_cheap_header_omits_commits_until_full_context_render(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
            }
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "SASE CONTEXT" not in header.plain
        assert "Commits:" not in header.plain

    def test_workflow_variables_keep_non_commit_meta_fields(self) -> None:
        agent = make_agent(
            step_output={
                "meta_commit_message": "fix: align",
                "meta_new_commit": "96a895335",
                "meta_commit_cwd": "/tmp/sase-core_4",
                "meta_commits": [
                    {
                        "message": "fix: align",
                        "sha": "96a895335",
                        "cwd": "/tmp/sase-core_4",
                    }
                ],
                "meta_result": "ready",
            }
        )

        header, _ = build_header_text(agent, summary=DetailHeaderSummary())

        assert "  Commits:\n" in header.plain
        assert "WORKFLOW VARIABLES\n" in header.plain
        assert "Result: ready\n" in header.plain
        assert "Commit Message:" not in header.plain
        assert "New Commit:" not in header.plain
        assert "Commit Cwd:" not in header.plain
        assert header.plain.index("WORKFLOW VARIABLES") < header.plain.index(
            "SASE CONTEXT"
        )

    def test_header_absent_when_no_meta_fields(self) -> None:
        agent = make_agent(step_output={"status": "ok"})

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert "Commits:" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1

    def test_header_absent_when_no_step_output(self) -> None:
        agent = make_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert "WORKFLOW VARIABLES" not in header.plain
        assert "Commits:" not in header.plain
        assert header.plain.count(MAJOR_SECTION_RULE) == 1
