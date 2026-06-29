"""Tests for agent list status and indicator rendering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestAgentListRevertedIndicator:
    def test_root_row_renders_reverted_badge_and_struck_name(self) -> None:
        agent = make_agent(status="DONE", reverted=True, llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=True)

        assert "↺ test_cl (DONE)" in left.plain
        name_start = left.plain.index("test_cl")
        name_end = name_start + len("test_cl")
        assert any(
            span.start <= name_start
            and span.end >= name_end
            and "strike" in str(span.style).lower()
            and "bold" in str(span.style).lower()
            and "#00d7af" in str(span.style).lower()
            for span in left.spans
        )

    def test_workflow_child_omits_reverted_indicator(self) -> None:
        agent = make_agent(
            status="DONE",
            reverted=True,
            parent_workflow="parent",
            step_type="agent",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "↺" not in left.plain
        name_start = left.plain.index("test_cl")
        name_end = name_start + len("test_cl")
        assert not any(
            span.start <= name_start
            and span.end >= name_end
            and "strike" in str(span.style).lower()
            for span in left.spans
        )

    def test_normal_row_omits_reverted_indicator(self) -> None:
        agent = make_agent(status="DONE", llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "↺" not in left.plain


class TestAgentListAutoApproveIcon:
    def test_normal_auto_approve_renders_bare_bolt(self) -> None:
        agent = make_agent(approve=True, llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡ ")
        assert "⚡E" not in left.plain
        assert "⚡T" not in left.plain
        assert "test_cl (RUNNING)" in left.plain

    def test_tale_auto_approve_renders_bolt_t(self) -> None:
        agent = make_agent(
            approve=True, auto_approve_plan_action="tale", llm_provider=None
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡T ")
        assert "test_cl (RUNNING)" in left.plain

    def test_epic_auto_approve_renders_bolt_e(self) -> None:
        agent = make_agent(
            approve=True, auto_approve_plan_action="epic", llm_provider=None
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡E ")
        assert "test_cl (RUNNING)" in left.plain

    def test_non_approve_row_omits_bolt(self) -> None:
        agent = make_agent(llm_provider=None)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "⚡" not in left.plain


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

        assert "Wait: until " in header.plain
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


class TestStoppedStatusRendering:
    def test_agent_row_renders_stopped_status_with_glyph_and_style(self) -> None:
        agent = make_agent(status=STOPPED_STATUS)

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        stopped_text = f"{STOPPED_GLYPH} {STOPPED_STATUS}"
        assert f"({stopped_text})" in left.plain
        status_start = left.plain.index(stopped_text)
        status_end = status_start + len(stopped_text)
        assert any(
            span.start <= status_start
            and span.end >= status_end
            and str(span.style) == f"bold {STOPPED_COLOR}"
            for span in left.spans
        )
