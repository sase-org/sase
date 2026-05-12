"""Tests for agent display list and phase rendering."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_header_text,
    render_phase_divider,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestAgentListBeadBadge:
    def test_phase_agent_row_renders_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.3" in left.plain

    def test_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x.land")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x.land" in left.plain

    def test_exact_land_agent_row_renders_epic_bead_badge(self) -> None:
        agent = make_agent(agent_name="sase-x")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @sase-x" in left.plain

    def test_dismissed_phase_agent_row_renders_underlying_bead_badge(self) -> None:
        agent = make_agent(agent_name="260428.sase-x.3")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert " ◆ @260428.sase-x.3" in left.plain

    def test_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="reviewer")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain

    def test_dotted_ordinary_agent_row_omits_bead_badge(self) -> None:
        agent = make_agent(agent_name="aij.2")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "◆" not in left.plain
        assert "@aij.2" in left.plain

    def test_bead_badge_flows_from_fold_annotation_to_agent_name(self) -> None:
        agent = make_agent(agent_name="sase-x.3", tag="pinned")

        left, _, _ = format_agent_option(
            agent, 0, is_selected=False, fold_annotation="×3"
        )

        assert "(RUNNING)×3 ◆ @sase-x.3" in left.plain
        assert "@pinned" not in left.plain


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "WAITING (until " in left.plain
        assert "," in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Waiting for: until " in header.plain
        assert " left)" in header.plain


class TestStartingStatusRendering:
    def test_agent_row_renders_starting_status_with_distinct_style(self) -> None:
        agent = make_agent(status="STARTING")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "(STARTING)" in left.plain
        status_start = left.plain.index("STARTING")
        status_end = status_start + len("STARTING")
        assert any(
            span.start <= status_start
            and span.end >= status_end
            and str(span.style) == "bold #87D7FF"
            for span in left.spans
        )


# -- provider emoji badges ----------------------------------------------------


class TestAgentListProviderEmojiBadges:
    def test_root_row_renders_opencode_provider_emoji_before_name(self) -> None:
        agent = make_agent(cl_name="root-agent", llm_provider="opencode")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "🐙 root-agent (RUNNING)" in left.plain

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

        assert "1/2 🤖 child-agent (RUNNING)" in left.plain

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
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/2 🐚 diff (RUNNING)" in left.plain
        assert "🎭" not in left.plain

    def test_row_without_provider_omits_provider_emoji(self) -> None:
        agent = make_agent(cl_name="plain-agent", llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain == "[agent] plain-agent (RUNNING)"
        assert not any(emoji in left.plain for emoji in ("🎭", "♊", "🤖", "🐼", "🐙"))


# -- _render_phase_divider ----------------------------------------------------


class TestRenderPhaseDivider:
    def test_contains_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1, 14, 23, 45))
        assert "PLANNER" in divider.plain

    def test_contains_time_format(self) -> None:
        divider = render_phase_divider("CODER", datetime(2024, 1, 1, 14, 23, 45))
        assert re.search(r"\d{2}:\d{2}:\d{2}", divider.plain)

    def test_none_start_time(self) -> None:
        divider = render_phase_divider("AGENT", None)
        assert "??:??:??" in divider.plain

    def test_bold_purple_label(self) -> None:
        divider = render_phase_divider("PLANNER", datetime(2024, 1, 1))
        has_bold = any(
            "bold" in str(s.style) and "af87ff" in str(s.style).lower()
            for s in divider._spans
        )
        assert has_bold


# -- workflow step-type glyphs -------------------------------------------------


class TestWorkflowStepTypeGlyph:
    def _make_child(self, step_type: str) -> Agent:
        return make_agent(
            parent_workflow="olcr",
            step_name=step_type,
            step_type=step_type,
            step_index=0,
            total_steps=3,
        )

    def test_python_step_renders_snake_glyph(self) -> None:
        agent = self._make_child("python")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/3 \U0001f40d " in left.plain

    def test_bash_step_renders_shell_glyph(self) -> None:
        agent = self._make_child("bash")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "1/3 \U0001f41a " in left.plain

    def test_agent_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("agent")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "\U0001f40d" not in left.plain
        assert "\U0001f41a" not in left.plain

    def test_parallel_step_has_no_step_type_glyph(self) -> None:
        agent = self._make_child("parallel")

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "\U0001f40d" not in left.plain
        assert "\U0001f41a" not in left.plain


# -- followup_agents field -----------------------------------------------------
