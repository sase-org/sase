"""Ownership copies of the Agents-tab row graph."""

from __future__ import annotations

import time
from datetime import datetime

from sase.ace.tui.models._agent_graph import (
    AGENT_RELINK_FIELDS,
    copy_agent_graph,
    copy_agent_rows_relinked,
)
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agents_tab_query_helpers import _make_agent


def _agent_session_cycle() -> tuple[Agent, Agent]:
    root = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="fam-root",
        raw_suffix="20260918080000",
        status="RUNNING",
        llm_provider="claude",
        agent_session="fam",
        agent_session_role="root",
        plan_chain_root=True,
    )
    child = _make_agent(
        cl_name="fam-code",
        raw_suffix="20260918080100",
        status="RUNNING",
        llm_provider="codex",
        parent_timestamp="20260918080000",
        agent_session="fam",
        agent_session_role="code",
    )
    root.followup_agents = [child]
    root.runtime_children = [child]
    child.agent_session_container = root
    child.wait_display_source = root
    child.retry_chain_siblings = [root]
    return root, child


def test_copy_preserves_agent_session_aliases_without_live_aliases() -> None:
    root, child = _agent_session_cycle()
    memo: dict[int, Agent] = {}
    copied_root = copy_agent_graph([root], memo)[0]
    copied_child = memo[id(child)]

    assert copied_root is not root
    assert copied_child is not child
    assert copied_root.followup_agents[0] is copied_child
    assert copied_root.runtime_children[0] is copied_child
    assert copied_child.agent_session_container is copied_root
    assert copied_child.wait_display_source is copied_root
    assert copied_child.retry_chain_siblings[0] is copied_root
    assert copied_child.agent_session_container is not root
    assert child.agent_session_container is root


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
        member.agent_session_container = container
    graph = [container, *members]
    memo: dict[int, Agent] = {}
    copied = copy_agent_graph(graph, memo)
    again = copy_agent_graph(graph, memo)

    assert len(memo) == 13
    assert [agent.identity for agent in copied] == [agent.identity for agent in graph]
    assert again[0] is copied[0]
    assert copied[0].runtime_children[0] is copied[1]
    assert copied[1].agent_session_container is copied[0]
    assert container.runtime_children[0] is members[0]


def test_copy_and_small_delta_cost_scale_with_unique_rows() -> None:
    """Measure copy cost; do not assert wall-clock bounds."""
    members = [
        _make_agent(
            cl_name=f"member-{index}",
            raw_suffix=f"2026091810{index:02d}00",
            start_time=datetime(2026, 9, 18, 10, index % 60, 0),
            agent_clan="bench-clan",
            agent_session="fam" if index % 4 == 0 else None,
            llm_provider="claude" if index % 2 == 0 else "codex",
        )
        for index in range(80)
    ]
    for index, member in enumerate(members):
        if index % 4 == 0 and index + 1 < len(members):
            member.followup_agents = [members[index + 1]]
            members[index + 1].agent_session_container = member
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


def test_relinked_rows_resolve_in_batch_references() -> None:
    root, child = _agent_session_cycle()
    root.wait_display_source = child
    root.status_display_source = child
    copied_root, copied_child = copy_agent_rows_relinked([root, child])

    assert copied_root is not root
    assert copied_child is not child
    assert copied_root.followup_agents == [copied_child]
    assert copied_root.followup_agents[0] is copied_child
    assert copied_root.runtime_children[0] is copied_child
    assert copied_root.wait_display_source is copied_child
    assert copied_root.status_display_source is copied_child
    assert copied_child.agent_session_container is copied_root
    assert copied_child.wait_display_source is copied_root
    assert copied_child.retry_chain_siblings[0] is copied_root


def test_relinked_rows_preserve_out_of_batch_reference() -> None:
    inside = _make_agent(cl_name="inside", raw_suffix="20260918130000")
    outside = _make_agent(cl_name="outside", raw_suffix="20260918130100")
    inside.wait_display_source = outside
    inside.runtime_children = [outside]
    (copied,) = copy_agent_rows_relinked([inside])

    assert copied.wait_display_source is outside
    assert copied.runtime_children == [outside]
    assert copied.runtime_children[0] is outside
    assert copied.runtime_children is not inside.runtime_children


def test_relinked_duplicate_rows_stay_aliased() -> None:
    agent = _make_agent(cl_name="dup", raw_suffix="20260918130200")
    first, second = copy_agent_rows_relinked([agent, agent])

    assert first is second
    assert first is not agent


def test_relinked_copies_do_not_alias_live_rows() -> None:
    root, child = _agent_session_cycle()
    original_status = root.status
    original_children = list(root.runtime_children)
    copied_root = copy_agent_rows_relinked([root, child])[0]

    assert copied_root.runtime_children is not root.runtime_children
    copied_root.status = "QUEUED"
    assert root.status == original_status
    copied_root.runtime_children.append(
        _make_agent(cl_name="extra", raw_suffix="20260918130300")
    )
    assert root.runtime_children == original_children
    assert len(root.runtime_children) == 1


def test_relinked_field_tuple_matches_agent_reference_fields() -> None:
    import dataclasses
    import re

    expected = {
        field.name
        for field in dataclasses.fields(Agent)
        if re.search(r"\bAgent\b", str(field.type))
    }
    assert set(AGENT_RELINK_FIELDS) == expected
