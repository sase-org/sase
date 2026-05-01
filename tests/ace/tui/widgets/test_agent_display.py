"""Tests for agent display helpers and followup_agents integration."""

from __future__ import annotations

import re
from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _derive_agent_bead_id,
    build_header_text,
    get_phase_label,
    render_phase_divider,
)


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for testing."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.gp",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


# -- _get_phase_label ---------------------------------------------------------


class TestGetPhaseLabel:
    def test_plan(self) -> None:
        agent = _make_agent(role_suffix=".plan")
        assert get_phase_label(agent) == "PLANNER"

    def test_code(self) -> None:
        agent = _make_agent(role_suffix=".code")
        assert get_phase_label(agent) == "CODER"

    def test_questions(self) -> None:
        agent = _make_agent(role_suffix=".q")
        assert get_phase_label(agent) == "QUESTIONS"

    def test_epic(self) -> None:
        agent = _make_agent(role_suffix=".epic")
        assert get_phase_label(agent) == "EPIC"

    def test_feedback_round_2(self) -> None:
        agent = _make_agent(role_suffix=".2")
        assert get_phase_label(agent) == "PLANNER (round 2)"

    def test_feedback_round_10(self) -> None:
        agent = _make_agent(role_suffix=".10")
        assert get_phase_label(agent) == "PLANNER (round 10)"

    def test_no_suffix(self) -> None:
        agent = _make_agent(role_suffix=None)
        assert get_phase_label(agent) == "AGENT"

    def test_unknown_suffix(self) -> None:
        agent = _make_agent(role_suffix=".xyz")
        assert get_phase_label(agent) == "AGENT"


# -- _derive_agent_bead_id / header metadata ---------------------------------


class TestAgentBeadMetadata:
    def test_phase_agent_name_renders_bead(self) -> None:
        agent = _make_agent(agent_name="sase-x.3")

        assert _derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_land_agent_name_renders_epic_bead(self) -> None:
        agent = _make_agent(agent_name="sase-x.land")

        assert _derive_agent_bead_id(agent) == "sase-x"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @sase-x.land\nBead: sase-x\n" in header.plain

    def test_dismissed_phase_agent_name_uses_underlying_bead(self) -> None:
        agent = _make_agent(agent_name="260428.sase-x.3")

        assert _derive_agent_bead_id(agent) == "sase-x.3"
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @260428.sase-x.3\nBead: sase-x.3\n" in header.plain

    def test_ordinary_agent_name_omits_bead(self) -> None:
        agent = _make_agent(agent_name="reviewer")

        assert _derive_agent_bead_id(agent) is None
        header, _ = build_header_text(agent, cheap=True)

        assert "Name: @reviewer\n" in header.plain
        assert "Bead:" not in header.plain


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


# -- followup_agents field -----------------------------------------------------


class TestFollowupAgentsField:
    def test_defaults_empty(self) -> None:
        assert _make_agent().followup_agents == []

    def test_excluded_from_bundle(self) -> None:
        agent = _make_agent()
        agent.followup_agents.append(_make_agent(cl_name="child"))
        assert "followup_agents" not in agent.to_bundle_dict()

    def test_roundtrip_resets(self) -> None:
        agent = _make_agent()
        agent.followup_agents.append(_make_agent(cl_name="child"))
        restored = Agent.from_bundle_dict(agent.to_bundle_dict())
        assert restored.followup_agents == []


# -- _apply_status_overrides followup population ------------------------------


class TestLoaderFollowupPopulation:
    def test_coder_attached_to_parent(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        coder = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
        )
        _apply_status_overrides([parent, coder])
        assert len(parent.followup_agents) == 1
        assert parent.followup_agents[0] is coder

    def test_feedback_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        fb = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
        )
        _apply_status_overrides([parent, fb])
        assert len(parent.followup_agents) == 1
        assert parent.followup_agents[0] is fb

    def test_sorted_chronologically(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        coder = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
            start_time=datetime(2024, 1, 1, 16, 0),
        )
        fb = _make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
            start_time=datetime(2024, 1, 1, 15, 0),
        )
        _apply_status_overrides([parent, coder, fb])
        assert parent.followup_agents[0] is fb
        assert parent.followup_agents[1] is coder

    def test_workflow_child_not_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        step = _make_agent(
            parent_timestamp="20240101142345",
            parent_workflow="test_wf",
            step_type="agent",
            status="DONE",
        )
        _apply_status_overrides([parent, step])
        assert parent.followup_agents == []
