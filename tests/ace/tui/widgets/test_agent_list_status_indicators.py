"""Tests for general agent list status and indicator rendering."""

from __future__ import annotations

from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
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
        assert "test_cl" not in left.plain
        assert not any("strike" in str(span.style).lower() for span in left.spans)

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


class TestAgentListFleetMarker:
    def test_remote_rows_do_not_use_star_shape_for_follow_state(self) -> None:
        followed = make_agent(
            fleet_origin_alias="apollo",
            fleet_followed=True,
            llm_provider=None,
        )
        unfollowed = make_agent(
            fleet_origin_alias="apollo",
            fleet_followed=False,
            llm_provider=None,
        )

        followed_left, _, _ = format_agent_option(followed, 0, is_selected=False)
        unfollowed_left, _, _ = format_agent_option(unfollowed, 1, is_selected=False)

        assert "★apollo" not in followed_left.plain
        assert "☆apollo" not in unfollowed_left.plain
        assert followed_left.plain == unfollowed_left.plain

    def test_unified_rows_chip_remote_nodes_never_local(self) -> None:
        local = make_agent(llm_provider=None)
        remote = make_agent(
            fleet_origin_alias="apollo",
            fleet_followed=True,
            llm_provider=None,
        )

        local_left, _, _ = format_agent_option(
            local,
            0,
            is_selected=False,
            show_machine_chip=True,
        )
        remote_left, _, _ = format_agent_option(
            remote,
            1,
            is_selected=False,
            show_machine_chip=True,
        )

        assert "here " not in local_left.plain
        assert remote_left.plain.startswith("apollo ")
        assert "★apollo" not in remote_left.plain

    def test_grouped_unified_rows_can_suppress_machine_chrome(self) -> None:
        remote = make_agent(
            fleet_origin_alias="apollo",
            fleet_followed=True,
            llm_provider=None,
        )

        remote_left, _, _ = format_agent_option(
            remote,
            0,
            is_selected=False,
            show_machine_chip=False,
        )

        assert "apollo" not in remote_left.plain

    def test_family_container_keeps_host_chip_member_shell_does_not(self) -> None:
        child = make_agent(
            parent_timestamp="20260509-100000",
            fleet_origin_alias="apollo",
            llm_provider=None,
            raw_suffix="20260509-100200",
        )
        root = make_agent(
            plan_chain_root=True,
            agent_family_role="root",
            fleet_origin_alias="apollo",
            llm_provider=None,
            raw_suffix="20260509-100000",
        )
        root.followup_agents = [child]
        assert root.is_family_container_row is True

        root_left, _, _ = format_agent_option(
            root,
            0,
            is_selected=False,
            show_machine_chip=True,
        )
        child_left, _, _ = format_agent_option(
            child,
            1,
            is_selected=False,
            show_machine_chip=True,
        )

        assert "apollo " in root_left.plain
        assert "apollo " not in child_left.plain

    def test_clan_container_keeps_host_chip(self) -> None:
        clan = make_agent(
            is_clan_container=True,
            agent_clan="map",
            fleet_origin_alias="apollo",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(
            clan,
            0,
            is_selected=False,
            show_machine_chip=True,
        )

        assert left.plain.startswith("apollo ")


class TestAgentListFleetSummaryChrome:
    def test_healthy_remote_row_renders_no_online_fresh_chrome(self) -> None:
        agent = make_agent(
            fleet_origin_alias="apollo",
            fleet_connection_health="online",
            fleet_freshness="fresh",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "online" not in left.plain
        assert "fresh" not in left.plain

    def test_offline_remote_row_still_renders_health_chrome(self) -> None:
        agent = make_agent(
            fleet_origin_alias="apollo",
            fleet_connection_health="offline",
            fleet_freshness="fresh",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "offline" in left.plain

    def test_stale_remote_row_still_renders_freshness_chrome(self) -> None:
        agent = make_agent(
            fleet_origin_alias="apollo",
            fleet_connection_health="online",
            fleet_freshness="stale",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "stale" in left.plain

    def test_healthy_remote_catalog_row_omits_bounded_intent_content(self) -> None:
        agent = make_agent(
            fleet_origin_alias="apollo",
            fleet_connection_health="online",
            fleet_freshness="fresh",
            fleet_bounded_intent="ship the fix",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "ship the fix" not in left.plain

    def test_dispatch_provisional_row_keeps_bounded_intent_content(self) -> None:
        agent = make_agent(
            fleet_origin_alias="apollo",
            fleet_connection_health="submission pending",
            fleet_freshness="submitted",
            fleet_bounded_intent="owner pending",
            fleet_dispatch_status="submitted",
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "owner pending" in left.plain

    def test_was_running_remote_row_renders_last_seen_label(self) -> None:
        from datetime import datetime

        agent = make_agent(
            status="WAS RUNNING",
            fleet_origin_alias="apollo",
            fleet_connection_health="offline",
            fleet_freshness="stale",
            fleet_observed_at_unix=1_800_000_720.0,
            stop_time=datetime.fromtimestamp(1_800_000_000.0),
            llm_provider=None,
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False)

        assert "last seen 12m ago" in left.plain


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
