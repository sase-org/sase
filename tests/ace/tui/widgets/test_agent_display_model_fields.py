"""Tests for transient agent relationship fields."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestFollowupAgentsField:
    def test_defaults_empty(self) -> None:
        assert make_agent().followup_agents == []

    def test_excluded_from_bundle(self) -> None:
        agent = make_agent()
        agent.followup_agents.append(make_agent(cl_name="child"))
        assert "followup_agents" not in agent.to_bundle_dict()

    def test_roundtrip_resets(self) -> None:
        agent = make_agent()
        agent.followup_agents.append(make_agent(cl_name="child"))
        restored = Agent.from_bundle_dict(agent.to_bundle_dict())
        assert restored.followup_agents == []


# -- runtime_children field ---------------------------------------------------


class TestRuntimeChildrenField:
    def test_defaults_empty(self) -> None:
        assert make_agent().runtime_children == []

    def test_excluded_from_bundle(self) -> None:
        agent = make_agent()
        agent.runtime_children.append(make_agent(cl_name="child"))
        assert "runtime_children" not in agent.to_bundle_dict()

    def test_roundtrip_resets(self) -> None:
        agent = make_agent()
        agent.runtime_children.append(make_agent(cl_name="child"))
        restored = Agent.from_bundle_dict(agent.to_bundle_dict())
        assert restored.runtime_children == []


# -- _apply_status_overrides followup population ------------------------------


class TestLoaderFollowupPopulation:
    def test_coder_attached_to_parent(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        parent.plan_chain_root = True
        coder = make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
        )
        _apply_status_overrides([parent, coder])
        assert len(parent.followup_agents) == 2
        assert coder in parent.followup_agents
        synthetic = next(
            child for child in parent.followup_agents if child is not coder
        )
        assert synthetic.is_synthetic_planner is True
        assert parent.is_family_container_row is True

    def test_feedback_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        fb = make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
        )
        _apply_status_overrides([parent, fb])
        assert len(parent.followup_agents) == 2
        assert fb in parent.followup_agents

    def test_sorted_chronologically(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        coder = make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".code",
            status="RUNNING",
            start_time=datetime(2024, 1, 1, 16, 0),
        )
        fb = make_agent(
            parent_timestamp="20240101142345",
            role_suffix=".2",
            status="DONE",
            start_time=datetime(2024, 1, 1, 15, 0),
        )
        _apply_status_overrides([parent, coder, fb])
        assert parent.followup_agents[0].role_suffix == "--plan"
        assert parent.followup_agents[1] is fb
        assert parent.followup_agents[2] is coder

    def test_workflow_child_not_attached(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides

        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            raw_suffix="20240101142345",
            role_suffix=".plan",
            status="DONE",
        )
        step = make_agent(
            parent_timestamp="20240101142345",
            parent_workflow="test_wf",
            step_type="agent",
            status="DONE",
        )
        _apply_status_overrides([parent, step])
        assert len(parent.followup_agents) == 1
        assert parent.followup_agents[0].role_suffix == "--plan"
        assert parent.followup_agents[0].is_synthetic_planner is True
        assert parent.is_family_container_row is False
