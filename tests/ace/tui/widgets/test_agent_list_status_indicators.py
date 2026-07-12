"""Tests for agent list status and indicator rendering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.models.agent import AgentType
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

    def test_workflow_child_auto_approve_renders_after_connector(self) -> None:
        agent = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="visual-workflow",
            parent_timestamp="20260509-100000-workflow",
            step_type="agent",
            approve=True,
            auto_approve_plan_action="epic",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("  └─ ⚡E ")
        assert left.plain.index("⚡E") > left.plain.index("└─")

    def test_workflow_child_auto_approve_keeps_connector_column_aligned(
        self,
    ) -> None:
        approved = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="visual-workflow",
            parent_timestamp="20260509-100000-workflow",
            step_type="agent",
            approve=True,
            auto_approve_plan_action="epic",
            llm_provider=None,
        )
        sibling = make_agent(
            agent_type=AgentType.WORKFLOW,
            parent_workflow="visual-workflow",
            parent_timestamp="20260509-100000-workflow",
            step_type="bash",
            llm_provider=None,
        )

        approved_left, _, _ = format_agent_option(approved, 0, is_selected=False)
        sibling_left, _, _ = format_agent_option(sibling, 1, is_selected=False)

        assert approved_left.plain.index("└─") == sibling_left.plain.index("└─")

    def test_root_auto_approve_keeps_leading_icon(self) -> None:
        agent = make_agent(
            approve=True,
            auto_approve_plan_action="epic",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert left.plain.startswith("⚡E ")


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_concise_wait_until_countdown_when_deps_done(
        self,
    ) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False, now=now)

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "until" not in left.plain
        assert "WAITING (" not in left.plain

    def test_agent_row_keeps_verbose_wait_until_when_deps_pending(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_until=wait_until,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=False,
        )

        assert "test_cl (WAITING (until 14:15, 1m29s))" in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Wait: until " in header.plain
        assert " left)" in header.plain


class TestRelativeWaitDurationRendering:
    def test_header_omits_duration_countdown_while_agent_deps_pending(self) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            start_time=datetime.now() + timedelta(minutes=5),
        )

        header, _ = build_header_text(agent, cheap=True)

        wait_line = next(
            line for line in header.plain.splitlines() if line.startswith("Wait: ")
        )
        assert wait_line == "Wait: dep + 5m"

    def test_agent_row_omits_duration_countdown_while_agent_deps_pending(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            start_time=datetime.now() + timedelta(minutes=5),
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_deps_satisfied=True,
        )

        assert left.plain.endswith("test_cl (WAITING +5m)")

    def test_agent_row_renders_duration_countdown_after_wait_until_written(
        self,
    ) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            wait_until=wait_until,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=True,
        )

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "+5m" not in left.plain

    def test_root_wait_display_source_renders_static_duration_hint(self) -> None:
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
        )
        root.wait_display_source = child

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert left.plain.endswith("test_cl (WAITING +5m)")

    def test_root_wait_display_source_renders_live_countdown(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
            wait_until=wait_until,
        )
        root.wait_display_source = child

        left, _, _ = format_agent_option(
            root,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=True,
        )

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "+5m" not in left.plain

    def test_root_wait_display_source_header_matches_child(self) -> None:
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
        )
        root.wait_display_source = child

        root_header, _ = build_header_text(root, cheap=True)
        child_header, _ = build_header_text(child, cheap=True)

        root_wait = next(
            line for line in root_header.plain.splitlines() if line.startswith("Wait: ")
        )
        child_wait = next(
            line
            for line in child_header.plain.splitlines()
            if line.startswith("Wait: ")
        )
        assert root_wait == child_wait == "Wait: dep + 5m"

    def test_pure_duration_wait_still_renders_countdown(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31)
        agent = make_agent(
            status="WAITING",
            wait_duration=300,
            start_time=datetime(2026, 4, 11, 14, 10, 0),
        )
        header_agent = make_agent(
            status="WAITING",
            wait_duration=300,
            start_time=datetime.now(),
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False, now=now)
        header, _ = build_header_text(header_agent, cheap=True)

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "WAITING (" not in left.plain
        assert "Wait: 5m (" in header.plain
        assert " left)" in header.plain

    def test_family_child_header_renders_waiting_for_like_root_waiting_row(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            parent_timestamp="parent-ts",
            waiting_for=["parent"],
            wait_duration=120,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert agent.is_family_member_child
        assert "ChangeSpec: test_cl" in header.plain
        assert "Step: " not in header.plain
        assert "Wait: parent + 2m" in header.plain


class TestRunnerSlotWaitRendering:
    def test_config_gated_row_renders_running_count_over_cap(self) -> None:
        agent = make_agent(
            status="WAITING",
            wait_runners=9,
            wait_runners_explicit=False,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=10,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "test_cl (WAITING ▶10/10)" in left.plain

    def test_explicit_barrier_row_and_queue_detail_are_unambiguous(self) -> None:
        agent = make_agent(
            status="WAITING",
            wait_runners=0,
            wait_runners_explicit=True,
            slot_requested_at="2026-07-12T12:00:00Z",
            runner_slots_in_use=3,
            runner_slot_queue_position=2,
            runner_slot_queue_size=3,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)
        header, _ = build_header_text(agent, cheap=True)

        assert "test_cl (WAITING ▶3→0)" in left.plain
        assert (
            "Wait: runners ≤ 0 (drain barrier) · 3 runners still running"
            " · queue #2 of 3"
        ) in header.plain


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
