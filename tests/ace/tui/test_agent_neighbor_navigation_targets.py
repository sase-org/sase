"""Tests for agent neighbor index and lane projection semantics."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup

from ._agent_neighbor_navigation_helpers import NeighborApp, make_agent


def _fold_clans(
    complete: list[Agent],
    origin: Agent,
    *,
    collapsed_panel_keys: set[str | None] | None = None,
) -> NeighborApp:
    """Build the navigation harness from the real folded clan projection."""
    app = NeighborApp(
        complete,
        collapsed_panel_keys=collapsed_panel_keys,
    )
    app._agents, app._fold_counts = filter_agents_by_fold_state(
        complete,
        app._fold_manager,
    )
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        collapsed_panel_keys=app._collapsed_panel_keys,
    )
    app.current_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == origin.identity
    )
    app._invalidate_agent_panel_cache()
    return app


def _agent_session_lane(agent_session: str, *roles: str) -> list[Agent]:
    """Return an agent session root entry plus its member rows, root first."""
    root = make_agent(f"{agent_session}--plan", status="DONE")
    root.agent_session = agent_session
    root.agent_session_role = "root"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    members = []
    for role in roles:
        member = make_agent(f"{agent_session}--{role}", status="DONE")
        member.agent_session = agent_session
        member.agent_session_role = role
        member.parent_timestamp = root.raw_suffix
        members.append(member)
    root.followup_agents = list(members)
    return [root, *members]


def _clan_member(
    name: str,
    *,
    clan: str,
    generation: str,
    tribe: str | None = None,
) -> Agent:
    member = make_agent(name, tribe=tribe, status="DONE")
    member.agent_clan = clan
    member.agent_clan_generation = generation
    return member


def test_top_level_agent_session_lane_projection_lists_dotted_hood_mates() -> None:
    root, member = _agent_session_lane("fam", "code")
    helper = make_agent("fam.helper")
    other = make_agent("fam.other")
    app = NeighborApp([root, member, helper, other])

    panel = app.lane_neighbor_projection_for(root)

    assert panel is not None
    assert [row.agent.identity for row in panel.rows] == [
        helper.identity,
        other.identity,
    ]
    assert panel.suppressed_lane_member_count == 1
    assert member.identity not in {row.agent.identity for row in panel.rows}


def test_folded_clan_sole_neighbor_is_counted() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="one",
        tribe="alpha",
    )
    complete = project_clan_tree([origin, target])
    app = _fold_clans(complete, origin)

    assert app._selected_agent_neighbor_count(origin) == 1


def test_folded_clan_neighbor_respects_active_search() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="one",
    )
    app = _fold_clans(project_clan_tree([origin, target]), origin)
    app._agent_search_query = "name:foo.plan"

    assert app._selected_agent_neighbor_count(origin) == 0


def test_folded_clan_neighbor_excludes_starting_and_dismissed_members() -> None:
    origin = make_agent("foo.plan")
    starting = _clan_member(
        "foo.starting",
        clan="workers",
        generation="one",
    )
    starting.status = "STARTING"
    # An old start_time must not resurrect the row as a neighbor target.
    starting.start_time = datetime(2020, 1, 1, 0, 0, 0)
    dismissed = _clan_member(
        "foo.dismissed",
        clan="reviewers",
        generation="one",
    )
    complete = project_clan_tree([origin, starting, dismissed])
    app = _fold_clans(complete, origin)
    app._dismissed_agents.add(dismissed.identity)

    assert app._selected_agent_neighbor_count(origin) == 0


def test_folded_clan_neighbor_excludes_inner_agent_session_member() -> None:
    origin = make_agent("foo.other")
    agent_session = _clan_member(
        "foo.session--plan",
        clan="workers",
        generation="one",
    )
    agent_session.agent_session = "foo.session"
    child = make_agent("foo.session--code", status="DONE")
    child.agent_session = "foo.session"
    child.parent_timestamp = agent_session.raw_suffix
    agent_session.runtime_children = [child]
    complete = project_clan_tree([origin, agent_session, child])
    app = _fold_clans(complete, origin)

    index = app._agent_neighbor_index()
    identities = {
        target.identity for target in index.neighbor_targets_for(origin.identity)
    }

    assert agent_session.identity in identities
    assert child.identity not in identities


def test_folded_clan_neighbor_includes_expanded_inner_agent_session_member() -> None:
    origin = make_agent("foo.other")
    agent_session = _clan_member(
        "foo.session--plan",
        clan="workers",
        generation="one",
    )
    agent_session.agent_session = "foo.session"
    child = make_agent("foo.session--code", status="DONE")
    child.agent_session = "foo.session"
    child.parent_timestamp = agent_session.raw_suffix
    agent_session.runtime_children = [child]
    complete = project_clan_tree([origin, agent_session, child])
    app = _fold_clans(complete, origin)
    assert agent_session.raw_suffix is not None
    app._fold_manager.expand(agent_session.raw_suffix)

    identities = {
        target.identity
        for target in app._agent_neighbor_index().neighbor_targets_for(origin.identity)
    }

    assert agent_session.identity in identities
    assert child.identity in identities
