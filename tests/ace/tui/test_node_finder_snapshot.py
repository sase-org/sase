"""Owner-aware snapshot tests for the Node Finder row model."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.actions.agents._fold_scope import panel_fold_registry
from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.node_finder import (
    NodeFinderReason,
    NodeFinderRole,
    filter_node_finder,
)
from sase.feature_flags.snapshot import override_flags
from tests.ace.tui._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent,
    make_agent_session,
    make_clan,
)


def _started() -> datetime:
    return datetime(2026, 7, 26, 9, 0, 0)


class NodeFinderHarness(JumpHarness, EntryJumpModeMixin):
    """Jump harness plus the query/load owner state the snapshot reads."""

    def __init__(self, complete: list[Agent], container: Agent) -> None:
        super().__init__(complete, container)
        self._agent_search_query = ""
        self._agent_load_state = None
        self._hidden_count = 0
        self.hide_non_run_agents = False

    def _refilter_agents(self, **kwargs: object) -> None:
        super()._refilter_agents(**kwargs)
        if not getattr(self, "_agent_search_query", ""):
            return
        from sase.ace.tui.actions.agents._prospective_clan import (
            apply_active_agent_query,
        )
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._agents = apply_active_agent_query(self, self._agents)
        focused_key = (
            self._panel_group.focused_key
            if getattr(self._panel_group, "panel_keys", None)
            else None
        )
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=self._agent_panels_grouped,
        )
        if not self._agents:
            self.current_idx = 0
        else:
            self.current_idx = max(0, min(self.current_idx, len(self._agents) - 1))


def _expand_all(app: NodeFinderHarness, agents: list[Agent]) -> None:
    for agent in agents:
        key = agent_fold_key(agent)
        if key:
            app._fold_manager.expand(key)
            app._fold_manager.expand(key)
    app._refilter_agents()


def _node_rows(snap) -> list:
    return [row for row in snap.rows if row.role is NodeFinderRole.NODE]


def _by_name(snap, name: str):
    return next(row for row in _node_rows(snap) if row.name == name)


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
    members = [row for row in _node_rows(snap) if row.name != "research"]
    assert len(members) == 3
    for member in members:
        assert member.reasons == frozenset({NodeFinderReason.FOLDED})
        assert member.unmet_fold_count >= 1
        assert member.nearest_collapsed == "clan research"
    assert snap.hidden_count == 3


def test_collapsed_session_shells_name_the_session() -> None:
    started = _started()
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
    assert _by_name(snap, "fam").reasons == frozenset()
    for name in ("fam--mon1", "fam--gate"):
        row = _by_name(snap, name)
        assert row.reasons == frozenset({NodeFinderReason.FOLDED})
        assert row.nearest_collapsed == "session fam"


def test_collapsed_banner_hides_without_fold_reasons() -> None:
    projected, root, _child = make_agent_session(in_clan=False)
    app = NodeFinderHarness(projected, root)
    _expand_all(app, projected)
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
    child = next(row for row in _node_rows(snap) if row.identity == _child.identity)
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
        assert _by_name(snap, name).reasons == frozenset({NodeFinderReason.PANEL})
    assert _by_name(snap, "b1").reasons == frozenset()


def test_query_hidden_on_both_flag_branches() -> None:
    alpha1 = make_agent("alpha-one", tribe="alpha")
    beta = make_agent("beta-one", tribe="beta")
    complete = [alpha1, beta]
    for unified in (True, False):
        app = NodeFinderHarness(complete, alpha1)
        app._agent_search_query = "tribe:alpha"
        with override_flags(agents_unified_query=unified):
            app._refilter_agents()
            snap = build_node_finder_snapshot(app)
        assert snap.query == "tribe:alpha"
        assert _by_name(snap, "alpha-one").reasons == frozenset()
        assert _by_name(snap, "beta-one").reasons == frozenset({NodeFinderReason.QUERY})
        assert snap.query_hidden_count == 1


def test_folded_and_query_hidden_at_once() -> None:
    projected, container = make_clan(2)
    app = NodeFinderHarness(projected, container)
    app._agent_search_query = "tribe:alpha"
    with override_flags(agents_unified_query=False):
        app._refilter_agents()
        snap = build_node_finder_snapshot(app)
    member = _by_name(snap, "member-0")
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
    hidden_row = _by_name(snap, "hidden")
    visible_row = _by_name(snap, "visible")
    container_row = next(
        row for row in _node_rows(snap) if row.identity == container.identity
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

    assert [row.name for row in _node_rows(snap)] == ["visible"]
    assert snap.hidden_by_i_count == 0


def test_remote_fleet_row_is_listed() -> None:
    agent = make_agent("fleet-node")
    agent.fleet_origin_alias = "remote"
    agent.fleet_logical_key = "fleet-node-key"
    app = NodeFinderHarness([agent], agent)
    snap = build_node_finder_snapshot(app)
    assert _by_name(snap, "fleet-node").reasons == frozenset()


def _workflow_family() -> tuple[list[Agent], Agent, Agent, Agent, Agent]:
    started = _started()
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-wf",
        agent_name="wf",
        workflow="myflow",
    )
    bash = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="x",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="build",
        step_type="bash",
        step_index=0,
        total_steps=3,
        role_suffix="--build",
    )
    code = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="y",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf-step",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="code",
        step_type="agent",
        step_index=1,
        total_steps=3,
        role_suffix="--code",
    )
    pre = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="z",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-wf-pre",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="pre",
        step_type="python",
        step_index=0,
        total_steps=3,
        is_pre_prompt_step=True,
        role_suffix="--pre",
    )
    return [root, bash, code, pre], root, bash, code, pre


def test_non_agent_steps_are_context_only_or_omitted() -> None:
    complete, root, _bash, code, _pre = _workflow_family()
    app = NodeFinderHarness(complete, root)
    snap = build_node_finder_snapshot(app)
    names = [row.name for row in _node_rows(snap)]
    # The workflow root and its agent step are listed; bash/python/pre-prompt
    # steps have no jumpable descendants, so they are omitted.
    assert "wf" in names
    code_row = next(row for row in _node_rows(snap) if row.identity == code.identity)
    assert code_row.jumpable
    assert "x" not in names
    assert "z" not in names
    assert "the-bash-step" not in names


def test_synthetic_unknown_step_kind_is_excluded() -> None:
    complete, root, _bash, _code, _pre = _workflow_family()
    strange = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="q",
        project_file="/p/p.sase",
        status="DONE",
        start_time=_started(),
        raw_suffix="ts-wf-strange",
        parent_workflow="myflow",
        parent_timestamp="ts-wf",
        step_name="strange",
        step_type="quantum",
        step_index=2,
        total_steps=4,
        role_suffix="--strange",
    )
    app = NodeFinderHarness(complete + [strange], root)
    snap = build_node_finder_snapshot(app)
    assert "the-quantum-step" not in [row.name for row in _node_rows(snap)]
    assert "the-strange-step" not in [row.name for row in _node_rows(snap)]


def test_starting_dismissed_and_hidden_only_parents_omitted() -> None:
    started = _started()
    visible = make_agent("visible")
    starting = make_agent("starting")
    starting.status = "STARTING"
    gone = make_agent("gone")
    hidden_root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="h",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-hidden-root",
        agent_name="h",
        workflow="hidden-flow",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hs",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-hidden-step",
        parent_workflow="hidden-flow",
        parent_timestamp="ts-hidden-root",
        step_name="setup",
        step_type="python",
        step_index=0,
        total_steps=1,
        is_hidden_step=True,
        role_suffix="--setup",
    )
    complete = [visible, starting, gone, hidden_root, hidden_step]
    app = NodeFinderHarness(complete, visible)
    app._dismissed_agents = {gone.identity}
    snap = build_node_finder_snapshot(app)
    names = [row.name for row in _node_rows(snap)]
    assert "visible" in names
    assert "starting" not in names
    assert "gone" not in names
    assert "h" not in names
    assert "the-setup-step" not in names


def test_identities_unique_and_expanded_order_matches_tab() -> None:
    projected, container = make_clan(3)
    app = NodeFinderHarness(projected, container)
    _expand_all(app, projected)
    snap = build_node_finder_snapshot(app)
    identities = [row.identity for row in _node_rows(snap)]
    assert len(set(identities)) == len(identities)
    assert [row.name for row in _node_rows(snap)] == [
        agent.agent_name or agent.agent_clan for agent in app._agents
    ]


def test_snapshot_filter_hints_map_to_identities() -> None:
    projected, container = make_clan(3)
    app = NodeFinderHarness(projected, container)
    snap = build_node_finder_snapshot(app)
    view = filter_node_finder(snap, "")
    assert len(view.hint_to_identity) == snap.node_count
    assert set(view.hint_to_identity.values()) == {
        row.identity for row in _node_rows(snap) if row.jumpable
    }
    member_view = filter_node_finder(snap, "member-1")
    assert [row.name for row in member_view.rows if row.jumpable] == ["member-1"]
