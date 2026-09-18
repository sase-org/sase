"""Fixtures for Agents-tab worker/UI graph isolation tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models._agent_status_apply import apply_status_overrides
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers
from sase.ace.tui.widgets._agent_list_render_agent_prefix import append_agent_row_prefix

from tests._agents_tab_query_helpers import _make_agent


def row_prefix(agent: Agent) -> str:
    """Return the visible leading chrome for *agent*."""
    return str(append_agent_row_prefix(agent, is_selected=False))


def row_observation(agent: Agent) -> dict[str, object]:
    """Explicit presentation fields used as a graph oracle."""
    return {
        "identity": agent.identity,
        "status": agent.status,
        "status_bucket": agent.status_bucket,
        "providers": ordered_row_providers(agent),
        "followup": tuple(child.identity for child in agent.followup_agents),
        "runtime_children": tuple(child.identity for child in agent.runtime_children),
        "family_container": (
            None if agent.family_container is None else agent.family_container.identity
        ),
        "wait_display_source": (
            None
            if agent.wait_display_source is None
            else agent.wait_display_source.identity
        ),
        "is_family_container_row": agent.is_family_container_row,
        "llm_provider": agent.llm_provider,
    }


def normalize_agent_graph(agents: list[Agent]) -> list[Agent]:
    apply_status_overrides(agents, classify_diff_badges=False)
    return sort_and_reorder(agents, [])


def clan_graph() -> list[Agent]:
    claude = _make_agent(
        cl_name="epic-claude",
        raw_suffix="20260918090100",
        status="RUNNING",
        llm_provider="claude",
        agent_clan="epic-clan",
        agent_clan_generation="g1",
        tribe="epic",
        start_time=datetime(2026, 9, 18, 9, 1, 0),
        run_start_time=datetime(2026, 9, 18, 9, 1, 0),
    )
    codex = _make_agent(
        cl_name="epic-codex",
        raw_suffix="20260918090200",
        status="RUNNING",
        llm_provider="codex",
        agent_clan="epic-clan",
        agent_clan_generation="g1",
        tribe="epic",
        start_time=datetime(2026, 9, 18, 9, 2, 0),
        run_start_time=datetime(2026, 9, 18, 9, 2, 0),
    )
    return normalize_agent_graph([claude, codex])


def family_graph() -> list[Agent]:
    root = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="fam-root",
        raw_suffix="20260918080000",
        status="RUNNING",
        llm_provider="claude",
        agent_name="fam",
        agent_family="fam",
        agent_family_role="root",
        plan_chain_root=True,
        role_suffix="--plan",
        workflow="ace(run)",
        start_time=datetime(2026, 9, 18, 8, 0, 0),
        run_start_time=datetime(2026, 9, 18, 8, 0, 0),
        tribe="epic",
    )
    coder = _make_agent(
        cl_name="fam-code",
        raw_suffix="20260918080100",
        status="RUNNING",
        llm_provider="codex",
        parent_timestamp="20260918080000",
        agent_name="fam-code",
        agent_family="fam",
        agent_family_role="code",
        role_suffix="--code",
        start_time=datetime(2026, 9, 18, 8, 1, 0),
        run_start_time=datetime(2026, 9, 18, 8, 1, 0),
        tribe="epic",
    )
    return normalize_agent_graph([root, coder])


def unrelated_delta() -> Agent:
    return _make_agent(
        cl_name="unrelated",
        raw_suffix="20260918100000",
        status="DONE",
        start_time=datetime(2026, 9, 18, 10, 0, 0),
    )


def delta_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_delta",
        used_artifact_index=False,
    )


def clan_container(agents: list[Agent]) -> Agent:
    return next(agent for agent in agents if agent.is_clan_container)


def family_root(agents: list[Agent]) -> Agent:
    return next(agent for agent in agents if agent.is_family_container_row)
