"""Hidden-reason snapshot tests: fold, banner, panel, query, and I-hidden rows."""

from __future__ import annotations

from datetime import timedelta

from sase.ace.tui.actions.agents._fold_scope import panel_fold_registry
from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.node_finder import NodeFinderReason
from tests.ace.tui._member_jump_navigation_helpers import (
    make_agent,
    make_agent_session,
    make_clan,
)
from tests.ace.tui._node_finder_snapshot_shared import (
    NodeFinderHarness,
    expand_all_nodes,
    snapshot_node_rows,
    snapshot_row_by_name,
    snapshot_started,
)

__all__ = [
    "test_collapsed_banner_hides_without_fold_reasons",
    "test_collapsed_clan_member_is_fold_hidden",
    "test_collapsed_panel_marks_rows",
    "test_collapsed_session_turns_name_the_session",
    "test_folded_and_query_hidden_at_once",
    "test_i_hidden_rows_use_the_pre_hide_roster_and_keep_tree_position",
    "test_i_hidden_snapshot_omits_dismissed_and_explicitly_removed_rows",
    "test_query_hidden_marks_nonmatching_rows",
    "test_remote_fleet_row_is_listed",
    "test_visible_row_carries_here_and_no_reasons",
]


def test_visible_row_carries_here_and_no_reasons() -> None:
    solo = make_agent("solo")
    app = NodeFinderHarness([solo], solo)
    snap = build_node_finder_snapshot(app)
    assert snap.here_row is not None
    row = snap.rows[snap.here_row]
    assert row.name == "solo"
    assert row.is_here
    assert row.reasons == frozenset()
    assert snap.node_count == 1
    assert snap.hidden_count == 0


def test_collapsed_clan_member_is_fold_hidden() -> None:
    projected, container = make_clan(3)
    app = NodeFinderHarness(projected, container)
    snap = build_node_finder_snapshot(app)
    members = [row for row in snapshot_node_rows(snap) if row.name != "research"]
    assert len(members) == 3
    for member in members:
        assert member.reasons == frozenset({NodeFinderReason.FOLDED})
        assert member.unmet_fold_count >= 1
        assert member.nearest_collapsed == "clan research"
    assert snap.hidden_count == 3


def test_collapsed_session_turns_name_the_session() -> None:
    started = snapshot_started()
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-root",
        agent_name="fam--0",
        agent_session="fam",
        agent_session_role="root",
        role_suffix="--0",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--mon1",
        project_file="/p/p.sase",
        status="MONITORING",
        start_time=started + timedelta(minutes=1),
        raw_suffix="ts-mon1",
        parent_timestamp="ts-root",
        agent_name="fam--mon1",
        agent_session="fam",
        agent_session_role="monitor",
        role_suffix="--mon1",
        monitor_id="mon-mon1",
    )
    gate = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--gate",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-gate",
        parent_timestamp="ts-root",
        agent_name="fam--gate",
        agent_session="fam",
        agent_session_role="gate",
        role_suffix="--gate",
        gate_id="g1",
    )
    root.followup_agents = [monitor, gate]
    complete = [root, monitor, gate]
    app = NodeFinderHarness(complete, root)
    snap = build_node_finder_snapshot(app)
    assert snapshot_row_by_name(snap, "fam").reasons == frozenset()
    for name in ("fam--mon1", "fam--gate"):
        row = snapshot_row_by_name(snap, name)
        assert row.reasons == frozenset({NodeFinderReason.FOLDED})
        assert row.nearest_collapsed == "session fam"


def test_collapsed_banner_hides_without_fold_reasons() -> None:
    projected, root, _child = make_agent_session(in_clan=False)
    app = NodeFinderHarness(projected, root)
    expand_all_nodes(app, projected)
    panel_agents = list(app._agents)
    tree = build_agent_tree(
        panel_agents, fold_registry=None, mode=GroupingMode.STANDARD
    )
    group_keys = [
        entry.group.group_key
        for entry in tree
        if entry.kind == "group" and entry.group is not None
    ]
    assert group_keys, "expected at least one grouping banner"
    registry = panel_fold_registry(app, None)
    assert registry.collapse(group_keys[0])
    app._refilter_agents()
    snap = build_node_finder_snapshot(app)
    child = next(
        row for row in snapshot_node_rows(snap) if row.identity == _child.identity
    )
    assert NodeFinderReason.BANNER in child.reasons
    assert NodeFinderReason.FOLDED not in child.reasons
    assert child.group_label


def test_collapsed_panel_marks_rows() -> None:
    alpha1 = make_agent("a1", tribe="alpha")
    alpha2 = make_agent("a2", tribe="alpha")
    beta = make_agent("b1", tribe="beta")
    complete = [alpha1, alpha2, beta]
    app = NodeFinderHarness(complete, alpha1)
    app._collapsed_panel_keys = {"alpha"}
    snap = build_node_finder_snapshot(app)
    for name in ("a1", "a2"):
        assert snapshot_row_by_name(snap, name).reasons == frozenset(
            {NodeFinderReason.PANEL}
        )
    assert snapshot_row_by_name(snap, "b1").reasons == frozenset()


def test_query_hidden_marks_nonmatching_rows() -> None:
    alpha1 = make_agent("alpha-one", tribe="alpha")
    beta = make_agent("beta-one", tribe="beta")
    complete = [alpha1, beta]
    app = NodeFinderHarness(complete, alpha1)
    app._agent_search_query = "tribe:alpha"
    app._refilter_agents()
    snap = build_node_finder_snapshot(app)
    assert snap.query == "tribe:alpha"
    assert snapshot_row_by_name(snap, "alpha-one").reasons == frozenset()
    assert snapshot_row_by_name(snap, "beta-one").reasons == frozenset(
        {NodeFinderReason.QUERY}
    )
    assert snap.query_hidden_count == 1


def test_folded_and_query_hidden_at_once() -> None:
    projected, container = make_clan(2)
    app = NodeFinderHarness(projected, container)
    app._agent_search_query = "tribe:alpha"
    app._refilter_agents()
    snap = build_node_finder_snapshot(app)
    member = snapshot_row_by_name(snap, "member-0")
    assert member.reasons == frozenset(
        {NodeFinderReason.FOLDED, NodeFinderReason.QUERY}
    )


def test_i_hidden_rows_use_the_pre_hide_roster_and_keep_tree_position() -> None:
    visible = make_agent("visible", clan="research")
    hidden = make_agent("hidden", clan="research")
    hidden.hidden = True
    full = project_clan_tree([visible, hidden])
    visible_only = project_clan_tree([visible])
    container = next(agent for agent in full if agent.is_clan_container)
    app = NodeFinderHarness(visible_only, visible_only[0])
    app._agents_local_with_children = full
    app._hideable_agents = [hidden]
    app.hide_non_run_agents = True
    app._refilter_agents()

    snap = build_node_finder_snapshot(app)
    hidden_row = snapshot_row_by_name(snap, "hidden")
    visible_row = snapshot_row_by_name(snap, "visible")
    container_row = next(
        row for row in snapshot_node_rows(snap) if row.identity == container.identity
    )

    assert NodeFinderReason.NON_RUN in hidden_row.reasons
    assert NodeFinderReason.FOLDED in hidden_row.reasons
    assert hidden_row.parent_row == snap.rows.index(container_row)
    assert visible_row.parent_row == hidden_row.parent_row
    assert snap.hidden_by_i_count == 1


def test_i_hidden_snapshot_omits_dismissed_and_explicitly_removed_rows() -> None:
    visible = make_agent("visible")
    dismissed = make_agent("dismissed")
    removed = make_agent("removed")
    dismissed.hidden = True
    removed.hidden = True
    app = NodeFinderHarness([visible], visible)
    app._agents_local_with_children = [visible]
    app._hideable_agents = [dismissed, removed]
    app.hide_non_run_agents = True
    app._dismissed_agents = {dismissed.identity}
    app.filter_explicitly_removed = lambda agents: [
        agent for agent in agents if agent.identity != removed.identity
    ]

    snap = build_node_finder_snapshot(app)

    assert [row.name for row in snapshot_node_rows(snap)] == ["visible"]
    assert snap.hidden_by_i_count == 0


def test_remote_fleet_row_is_listed() -> None:
    agent = make_agent("fleet-node")
    agent.fleet_origin_alias = "remote"
    agent.fleet_logical_key = "fleet-node-key"
    app = NodeFinderHarness([agent], agent)
    snap = build_node_finder_snapshot(app)
    assert snapshot_row_by_name(snap, "fleet-node").reasons == frozenset()
