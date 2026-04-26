"""Tests for j/k navigation across banner rows on the Agents tab.

When the global group fold collapses agents (level < 2) the focused
Agents-tab panel renders only banner rows.  The keyboard `j`/`k`
bindings must walk those banners in tree order, updating
``_current_group_key`` so the rendered highlight follows.  At level 2
the original flat-agent behavior must still hold (within the focused
panel).
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldState
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _StubApp(BasicNavigationMixin):
    """Minimal harness exercising ``_navigate_agents_panel`` in isolation."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        level: int = 2,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._group_fold_state = AgentGroupFoldState(level=level)
        self._current_group_key: tuple[str, ...] | None = None
        # Tests put every agent in the same panel (focused_key derived
        # from the first agent's tag) so navigation visits all of them.
        focused_key = agents[0].tag if agents else None
        self._panel_group = AgentPanelGroup.from_agents(agents, focused_key)

    def _agents_visible_order(self) -> list[int]:
        """Mirror :meth:`AgentsMixinCore._agents_visible_order` for tests."""
        from sase.ace.tui.models.agent_groups import build_agent_tree
        from sase.ace.tui.models.agent_panels import (
            agents_for_panel,
            panel_key_per_agent,
        )

        focused_key = self._panel_group.focused_key
        keys_per_agent = panel_key_per_agent(self._agents)
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == focused_key]
        panel_agents = agents_for_panel(self._agents, focused_key)
        tree = build_agent_tree(panel_agents, group_fold_level=2)
        return [
            global_indices[entry.agent_idx]
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]


def _agent(
    *,
    tag: str = "",
    project: str = "proj",
    cl: str = "demo",
    name: str = "alpha",
) -> Agent:
    """Build an Agent with controllable grouping keys.

    The project banner key is ``(parent_dir_name, cl_name)``, so we put
    the *project* discriminator in the parent directory of project_file.
    """
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag or None,
    )


def test_l0_j_cycles_through_project_banners() -> None:
    """Three project banners (different projects) within the focused panel."""
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(agents, level=0)
    app._current_group_key = ("p1", "cl1")

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p2", "cl2")
    assert app.current_idx == 1
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p3", "cl3")
    assert app.current_idx == 2
    # Wraps to first.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1")
    assert app.current_idx == 0


def test_l0_k_reverses_project_banner_cycle() -> None:
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(agents, level=0)
    app._current_group_key = ("p1", "cl1")

    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("p3", "cl3")
    assert app.current_idx == 2
    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("p2", "cl2")
    assert app.current_idx == 1


def test_l1_cycles_project_and_name_root_banners() -> None:
    """L1 fold: project + name-root banners visible.

    Each name-root has two entries — singletons would be suppressed at
    level 1, so duplicating per root keeps every banner in the cycle.
    """
    agents = [
        _agent(project="p1", cl="cl1", name="d.first"),
        _agent(project="p1", cl="cl1", name="d.second"),
        _agent(project="p1", cl="cl1", name="sase-r.first"),
        _agent(project="p1", cl="cl1", name="sase-r.second"),
    ]
    app = _StubApp(agents, level=1)
    app._current_group_key = ("p1", "cl1")

    keys: list[tuple[str, ...] | None] = []
    for _ in range(3):
        app._navigate_agents_panel(1)
        keys.append(app._current_group_key)
    # Name-root banners render in deterministic alpha order within the project.
    assert keys == [
        ("p1", "cl1", "d"),
        ("p1", "cl1", "sase-r"),
        ("p1", "cl1"),  # wrap to start
    ]


def test_l2_keeps_flat_agent_navigation() -> None:
    """At level 2 j/k must still cycle agents in visible order.

    Input order matches visible order (same project), so the cursor
    walks 0 -> 1 -> 2 -> 0.
    """
    agents = [
        _agent(name="a1"),
        _agent(name="b1"),
        _agent(name="c1"),
    ]
    app = _StubApp(agents, level=2, current_idx=0)
    app._current_group_key = ("stale",)

    app._navigate_agents_panel(1)
    assert app.current_idx == 1
    assert app._current_group_key is None
    app._navigate_agents_panel(1)
    assert app.current_idx == 2
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap


def test_l2_walks_visible_grouping_order_not_input_order() -> None:
    """Agents in scrambled project order render in alphabetical project order.

    Input ``[zeta, alpha, beta]`` (by project) renders as
    ``[alpha, beta, zeta]``.  j from the visually-first row (``alpha``,
    global idx 1) must advance to ``beta`` (idx 2), then ``zeta`` (idx 0),
    then wrap.
    """
    agents = [
        _agent(project="zeta", cl="z1", name="z1"),
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, level=2, current_idx=1)  # alpha — visually first

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # beta
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # zeta
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # wrap to alpha


def test_l2_workflow_children_inherit_parent_grouping_in_walk() -> None:
    """Workflow children render contiguous with their parent.

    Input ``[parent, unrelated, child_of_parent]``: the child inherits
    parent's grouping so the visible order is ``[parent, child, unrelated]``.
    """
    parent = _agent(project="alpha", cl="parent", name="parent")
    parent.raw_suffix = "ts_parent"
    unrelated = _agent(project="zeta", cl="unrelated", name="unrelated")
    child = _agent(project="proj", cl="step", name="parent.step1")
    child.parent_timestamp = "ts_parent"
    child.parent_workflow = "wf"
    agents = [parent, unrelated, child]

    app = _StubApp(agents, level=2, current_idx=0)  # parent

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # workflow child (visually contiguous)
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # unrelated
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap to parent


def test_unmatched_group_key_lands_on_first_banner() -> None:
    """If ``_current_group_key`` matches no visible banner, snap to first."""
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(agents, level=0)
    app._current_group_key = ("ghost",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1")
    assert app.current_idx == 0


def test_jk_at_l0_banner_moves_visible_highlight_to_l1_banner() -> None:
    """At fold level 1, advancing from an L0 (project) banner to the L1
    (name-root) banner must move the AgentList's rendered highlight, not
    just ``_current_group_key``.
    """
    from sase.ace.tui.widgets.agent_list import AgentList

    agents = [
        _agent(project="p1", cl="cl1", name="sase-r.first"),
        _agent(project="p1", cl="cl1", name="sase-r.second"),
        _agent(project="p1", cl="cl1", name="sase-q.first"),
        _agent(project="p1", cl="cl1", name="sase-q.second"),
    ]
    app = _StubApp(agents, level=1)
    app._current_group_key = ("p1", "cl1")  # L0 project banner

    widget = AgentList()
    widget.update_list(
        agents,
        current_idx=0,
        group_fold_level=1,
        current_group_key=app._current_group_key,
    )
    # Layout at L1: project (0), name-root sase-q (1), name-root sase-r (2).
    # Starts highlighted on the project banner.
    assert widget.highlighted == 0

    # Drive the action-level navigation: j moves to the next banner — the
    # first L1 name-root.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1", "sase-q")

    # The debounced refresh path then calls update_highlight with the
    # new group_key.  Before the fix this left the highlight on the L0
    # banner; after the fix it advances to the L1 banner row.
    local_idx = app.current_idx
    widget.update_highlight(local_idx, None, group_key=app._current_group_key)
    assert widget.highlighted == 1
