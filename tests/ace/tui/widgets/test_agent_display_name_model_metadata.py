"""Tests for agent display name and model metadata."""

from __future__ import annotations

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_metadata_prefix,
    assert_span_covers,
)


class TestAgentNameMetadata:
    def test_unnamed_agent_renders_unassigned_name_first(self) -> None:
        agent = make_agent()

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Name: ") == 1
        assert_metadata_prefix(header, "Name: unassigned")
        assert_span_covers(header, "unassigned", "dim")
        assert header.plain.index("Name: unassigned\n") < header.plain.index(
            "ChangeSpec:"
        )
        assert "Bead:" not in header.plain

    def test_named_agent_renders_name_first(self) -> None:
        agent = make_agent(agent_name="reviewer")

        header, _ = build_header_text(agent, cheap=True)

        assert header.plain.count("Name: ") == 1
        assert_metadata_prefix(header, "Name: reviewer")
        assert_span_covers(header, "reviewer", "#FFD700")
        assert header.plain.index("Name: reviewer\n") < header.plain.index(
            "ChangeSpec:"
        )

    def test_retry_chain_renders_name_before_retry_chain(self) -> None:
        agent = make_agent(
            agent_name="reviewer",
            retry_attempt=2,
            retry_error_category="rate_limit",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert_metadata_prefix(header, "Name: reviewer")
        assert "Retry chain: ↻ attempt #2 (rate_limit)\n" in header.plain
        assert header.plain.index("Name: reviewer\n") < header.plain.index(
            "Retry chain:"
        )


class TestAgentModelMetadata:
    def test_non_agent_workflow_child_omits_model(self) -> None:
        agent = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="diff",
            step_type="bash",
            step_index=0,
            total_steps=2,
            model="opus",
            llm_provider="claude",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Step: diff\n" in header.plain
        assert "Model:" not in header.plain

    def test_agent_workflow_child_renders_model(self) -> None:
        agent = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="write",
            step_type="agent",
            step_index=1,
            total_steps=2,
            model="opus",
            llm_provider="claude",
        )

        header, _ = build_header_text(agent, cheap=True)

        assert "Model: CLAUDE(opus)\n" in header.plain

    def test_top_level_agent_renders_model(self) -> None:
        agent = make_agent(model="opus", llm_provider="claude")

        header, _ = build_header_text(agent, cheap=True)

        assert "Model: CLAUDE(opus)\n" in header.plain
