"""Tests for agent list provider and workflow step glyph rendering."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestAgentListProviderEmojiBadges:
    def test_root_row_renders_child_provider_emojis_before_name(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        planner = make_agent(
            cl_name="planner",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        coder = make_agent(
            cl_name="coder",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 5, 0),
        )
        root.runtime_children.extend([planner, coder])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 root-agent (RUNNING)" in left.plain

    def test_root_row_provider_order_follows_first_run_time(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        agy = make_agent(
            cl_name="agy",
            llm_provider="agy",
            start_time=datetime(2024, 1, 1, 14, 6, 0),
        )
        codex = make_agent(
            cl_name="codex",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 3, 0),
        )
        claude = make_agent(
            cl_name="claude",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        root.runtime_children.extend([agy, codex, claude])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 🪐 root-agent (RUNNING)" in left.plain

    def test_root_row_deduplicates_provider_emojis(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        planner = make_agent(
            cl_name="planner",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        coder = make_agent(
            cl_name="coder",
            llm_provider="codex",
            start_time=datetime(2024, 1, 1, 14, 5, 0),
        )
        root.runtime_children.extend([planner, coder])

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🤖 root-agent (RUNNING)" in left.plain
        assert left.plain.count("🎭") == 1

    def test_root_row_skips_providerless_child_and_includes_grandchild(self) -> None:
        root = make_agent(
            cl_name="root-agent",
            llm_provider="claude",
            start_time=datetime(2024, 1, 1, 14, 0, 0),
        )
        child = make_agent(
            cl_name="child",
            llm_provider=None,
            start_time=datetime(2024, 1, 1, 14, 1, 0),
        )
        grandchild = make_agent(
            cl_name="grandchild",
            llm_provider="agy",
            start_time=datetime(2024, 1, 1, 14, 2, 0),
        )
        child.runtime_children.append(grandchild)
        root.runtime_children.append(child)

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert "🎭 🪐 root-agent (RUNNING)" in left.plain

    def test_root_row_renders_opencode_provider_emoji_before_name(self) -> None:
        agent = make_agent(cl_name="root-agent", llm_provider="opencode")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🐙 root-agent (RUNNING)" in left.plain

    def test_root_row_keeps_provider_before_name_and_moves_pencil_to_suffix(
        self,
    ) -> None:
        agent = make_agent(
            cl_name="root-agent",
            llm_provider="opencode",
            diff_path="/tmp/sase/demo.diff",
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🐙 root-agent (RUNNING)" in left.plain
        assert "✏️" not in left.plain
        assert suffix.plain == "✏️"

    def test_root_row_renders_qwen_provider_emoji_after_prefix_controls(self) -> None:
        agent = make_agent(cl_name="qwen-agent", llm_provider="qwen")

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            is_marked=True,
            hint_char="a",
        )

        assert left.plain.startswith("[a] [✓] [agent] 🐼 qwen-agent")

    def test_root_row_renders_grok_provider_emoji_before_name(self) -> None:
        agent = make_agent(cl_name="grok-agent", llm_provider="grok")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🛰️ grok-agent (RUNNING)" in left.plain

    def test_workflow_child_row_renders_codex_provider_emoji_before_name(self) -> None:
        agent = make_agent(
            cl_name="child-agent",
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="agent",
            step_type="agent",
            step_index=0,
            total_steps=2,
            llm_provider="codex",
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🤖 (RUNNING)" in left.plain
        assert "child-agent" not in left.plain
        assert "1/2" not in left.plain

    def test_non_agent_workflow_child_row_omits_provider_emoji(self) -> None:
        agent = make_agent(
            cl_name="diff",
            agent_type=AgentType.WORKFLOW,
            parent_workflow="wf",
            step_name="diff",
            step_type="bash",
            step_index=0,
            total_steps=2,
            llm_provider="claude",
            diff_path="/tmp/sase/demo.diff",
        )

        left, suffix, _ = format_agent_option(agent, 0, is_selected=False)

        assert "❯ diff (RUNNING)" in left.plain
        assert "1/2" not in left.plain
        assert "🎭" not in left.plain
        assert suffix.plain == "✏️"

    def test_row_without_provider_omits_provider_emoji(self) -> None:
        agent = make_agent(cl_name="plain-agent", llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain == "[agent] plain-agent (RUNNING)"
        assert not any(emoji in left.plain for emoji in ("🎭", "🪐", "🤖", "🐼", "🐙"))


class TestWorkflowStepTypeGlyph:
    def _make_child(self, step_type: str) -> Agent:
        return make_agent(
            parent_workflow="olcr",
            step_name=step_type,
            step_type=step_type,
            step_index=0,
            total_steps=3,
        )

    def test_python_step_renders_run_glyph(self) -> None:
        agent = self._make_child("python")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "❯ " in left.plain
        assert "1/3" not in left.plain

    def test_bash_step_renders_run_glyph(self) -> None:
        agent = self._make_child("bash")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "❯ " in left.plain
        assert "1/3" not in left.plain

    def test_agent_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("agent")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "❯" not in left.plain

    def test_parallel_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("parallel")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "❯" not in left.plain
