"""Rootless clan model and cleanup helpers."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._clan_cleanup import clan_members_for_container
from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts,
    aggregate_clan_status,
    clan_member_counts,
    clan_members,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(name: str, status: str, *, suffix: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        agent_clan="research",
        agent_clan_generation="20260717100000",
    )


def test_clan_aggregation_keys_members_on_agent_clan() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    running = _agent("research.one", "RUNNING", suffix="one")
    done = _agent("research.two", "DONE", suffix="two")
    outsider = _agent("other.one", "FAILED", suffix="other")
    outsider.agent_clan = "other"
    container.runtime_children = [running, done, outsider]

    assert clan_members(container) == (running, done)
    assert clan_member_counts(container) == ClanStatusCounts(running=1, done=1)
    assert aggregate_clan_status(
        member.status for member in clan_members(container)
    ) == ("RUNNING")


def test_cleanup_cascades_from_container_but_not_from_member() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    one = _agent("research.one", "RUNNING", suffix="one")
    two = _agent("research.two", "WAITING", suffix="two")
    agents = [container, one, two]

    assert clan_members_for_container(container, agents) == [one, two]
    assert clan_members_for_container(one, agents) == []
