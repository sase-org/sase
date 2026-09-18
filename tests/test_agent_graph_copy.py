"""Ownership copies of the Agents-tab row graph."""

from __future__ import annotations

import time
from datetime import datetime

from sase.ace.tui.models._agent_graph import copy_agent_graph
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agents_tab_query_helpers import _make_agent


def _family_cycle() -> tuple[Agent, Agent]:
    root = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="fam-root",
        raw_suffix="20260918080000",
        status="RUNNING",
        llm_provider="claude",
        agent_family="fam",
        agent_family_role="root",
        plan_chain_root=True,
    )
    child = _make_agent(
        cl_name="fam-code",
        raw_suffix="20260918080100",
        status="RUNNING",
        llm_provider="codex",
        parent_timestamp="20260918080000",
        agent_family="fam",
        agent_family_role="code",
    )
    root.followup_agents = [child]
    root.runtime_children = [child]
    child.family_container = root
    child.wait_display_source = root
    child.retry_chain_siblings = [root]
    return root, child


def test_copy_preserves_family_aliases_without_live_aliases() -> None:
    root, child = _family_cycle()
    memo: dict[int, Agent] = {}
    copied_root = copy_agent_graph([root], memo)[0]
    copied_child = memo[id(child)]

    assert copied_root is not root
    assert copied_child is not child
    assert copied_root.followup_agents[0] is copied_child
    assert copied_root.runtime_children[0] is copied_child
    assert copied_child.family_container is copied_root
    assert copied_child.wait_display_source is copied_root
    assert copied_child.retry_chain_siblings[0] is copied_root
    assert copied_child.family_container is not root
    assert child.family_container is root


def test_copy_shares_row_across_visible_and_capacity_rosters() -> None:
    visible = _make_agent(cl_name="shared", raw_suffix="20260918120000")
    other = _make_agent(cl_name="other", raw_suffix="20260918120100")
    visible.waiting_for = ["alpha"]
    memo: dict[int, Agent] = {}
    copied_visible = copy_agent_graph([visible, other], memo)
    copied_capacity = copy_agent_graph([visible], memo)

    assert copied_capacity[0] is copied_visible[0]
    assert copied_capacity[0] is not visible
    copied_visible[0].waiting_for.append("beta")
    assert visible.waiting_for == ["alpha"]
    assert copied_capacity[0].waiting_for == ["alpha", "beta"]


def test_copy_cost_is_bounded_by_unique_rows() -> None:
    members = [
        _make_agent(
            cl_name=f"member-{index}",
            raw_suffix=f"2026091809{index:02d}00",
            start_time=datetime(2026, 9, 18, 9, index, 0),
            agent_clan="epic-clan",
            tribe="epic",
        )
        for index in range(12)
    ]
    container = _make_agent(
        cl_name="epic-clan",
        raw_suffix=None,
        is_clan_container=True,
        agent_clan="epic-clan",
    )
    container.runtime_children = list(members)
    for member in members:
        member.family_container = container
    graph = [container, *members]
    memo: dict[int, Agent] = {}
    copied = copy_agent_graph(graph, memo)
    again = copy_agent_graph(graph, memo)

    assert len(memo) == 13
    assert [agent.identity for agent in copied] == [agent.identity for agent in graph]
    assert again[0] is copied[0]
    assert copied[0].runtime_children[0] is copied[1]
    assert copied[1].family_container is copied[0]
    assert container.runtime_children[0] is members[0]


def test_copy_and_small_delta_cost_scale_with_unique_rows() -> None:
    """Measure copy cost; do not assert wall-clock bounds."""
    members = [
        _make_agent(
            cl_name=f"member-{index}",
            raw_suffix=f"2026091810{index:02d}00",
            start_time=datetime(2026, 9, 18, 10, index % 60, 0),
            agent_clan="bench-clan",
            agent_family="fam" if index % 4 == 0 else None,
            llm_provider="claude" if index % 2 == 0 else "codex",
        )
        for index in range(80)
    ]
    for index, member in enumerate(members):
        if index % 4 == 0 and index + 1 < len(members):
            member.followup_agents = [members[index + 1]]
            members[index + 1].family_container = member
            members[index + 1].parent_timestamp = member.raw_suffix
    started = time.perf_counter()
    memo: dict[int, Agent] = {}
    copied = copy_agent_graph(members, memo)
    large_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    small = copy_agent_graph(members[:3], memo)
    small_ms = (time.perf_counter() - started) * 1000
    assert len(memo) == 80
    assert len(copied) == 80
    assert small[0] is copied[0]
    print(
        f"agent-graph copy: n=80 unique={len(memo)} large={large_ms:.3f}ms "
        f"repeat_small={small_ms:.3f}ms"
    )
