"""Tests for j/k navigation across banner rows on the Agents tab.

When some groups on the focused panel are collapsed, ``j`` / ``k`` must
walk every selectable stop — collapsed banners and visible agents — in
tree order, updating ``_current_group_key`` (banner) or ``current_idx``
(agent) so the rendered highlight follows.  When every group is
expanded the cycle reduces to flat agent navigation.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _StubApp(BasicNavigationMixin):
    """Minimal harness exercising ``_navigate_agents_panel`` in isolation."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        collapsed: list[tuple[str, ...]] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        self._current_group_key: tuple[str, ...] | None = None
        focused_key = agents[0].tag if agents else None
        self._panel_group = AgentPanelGroup.from_agents(agents, focused_key)

    def _agents_visible_order(self) -> list[int]:
        from sase.ace.tui.models.agent_groups import build_agent_tree
        from sase.ace.tui.models.agent_panels import (
            agents_for_panel,
            panel_key_per_agent,
        )

        focused_key = self._panel_group.focused_key
        keys_per_agent = panel_key_per_agent(self._agents)
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == focused_key]
        panel_agents = agents_for_panel(self._agents, focused_key)
        tree = build_agent_tree(panel_agents, fold_registry=self._group_fold_registry)
        return [
            global_indices[entry.agent_idx]
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _panel_navigation_stops(
        self,
    ) -> list[tuple[str, int | tuple[str, ...]]]:
        from sase.ace.tui.models.agent_groups import build_agent_tree
        from sase.ace.tui.models.agent_panels import (
            agents_for_panel,
            panel_key_per_agent,
        )

        focused_key = self._panel_group.focused_key
        keys_per_agent = panel_key_per_agent(self._agents)
        global_indices = [i for i, k in enumerate(keys_per_agent) if k == focused_key]
        panel_agents = agents_for_panel(self._agents, focused_key)
        tree = build_agent_tree(panel_agents, fold_registry=self._group_fold_registry)
        stops: list[tuple[str, int | tuple[str, ...]]] = []
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.is_collapsed:
                    stops.append(("banner", entry.group.group_key))
            elif entry.kind == "agent" and entry.agent_idx is not None:
                stops.append(("agent", global_indices[entry.agent_idx]))
        return stops


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


def test_all_collapsed_j_cycles_through_project_banners() -> None:
    """Every L0 collapsed: j cycles through project banners."""
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(
        agents,
        collapsed=[("p1", "cl1"), ("p2", "cl2"), ("p3", "cl3")],
    )
    app._current_group_key = ("p1", "cl1")

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p2", "cl2")
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p3", "cl3")
    # Wraps to first.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1")


def test_all_collapsed_k_reverses_project_banner_cycle() -> None:
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(
        agents,
        collapsed=[("p1", "cl1"), ("p2", "cl2"), ("p3", "cl3")],
    )
    app._current_group_key = ("p1", "cl1")

    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("p3", "cl3")
    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("p2", "cl2")


def test_mixed_state_walks_banners_and_agents() -> None:
    """Some groups collapsed, others expanded — j walks every selectable stop."""
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),  # collapsed
        _agent(project="p2", cl="cl2", name="b1"),  # expanded
        _agent(project="p3", cl="cl3", name="c1"),  # expanded
    ]
    app = _StubApp(
        agents,
        collapsed=[("p1", "cl1")],
        current_idx=1,
    )
    # Order of stops: banner(p1) -> agent(b1, idx 1) -> agent(c1, idx 2)
    app._navigate_agents_panel(1)
    assert app._current_group_key is None
    assert app.current_idx == 2  # next agent
    app._navigate_agents_panel(1)
    # Wraps onto the collapsed banner.
    assert app._current_group_key == ("p1", "cl1")
    app._navigate_agents_panel(1)
    assert app._current_group_key is None
    assert app.current_idx == 1  # back to first agent


def test_all_expanded_keeps_flat_agent_navigation() -> None:
    """No groups collapsed: j/k cycles agents in visible order."""
    agents = [
        _agent(name="a1"),
        _agent(name="b1"),
        _agent(name="c1"),
    ]
    app = _StubApp(agents, current_idx=0)
    app._current_group_key = ("stale",)  # stale focus is ignored

    app._navigate_agents_panel(1)
    assert app.current_idx == 1
    assert app._current_group_key is None
    app._navigate_agents_panel(1)
    assert app.current_idx == 2
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap


def test_walks_grouping_order_not_input_order() -> None:
    """Agents in scrambled project order render in alphabetical project order."""
    agents = [
        _agent(project="zeta", cl="z1", name="z1"),
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, current_idx=1)  # alpha — visually first

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # beta
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # zeta
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # wrap to alpha


def test_workflow_children_inherit_parent_grouping_in_walk() -> None:
    """Workflow children render contiguous with their parent."""
    parent = _agent(project="alpha", cl="parent", name="parent")
    parent.raw_suffix = "ts_parent"
    unrelated = _agent(project="zeta", cl="unrelated", name="unrelated")
    child = _agent(project="proj", cl="step", name="parent.step1")
    child.parent_timestamp = "ts_parent"
    child.parent_workflow = "wf"
    agents = [parent, unrelated, child]

    app = _StubApp(agents, current_idx=0)  # parent

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # workflow child (visually contiguous)
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # unrelated
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap to parent


def test_unmatched_group_key_lands_on_first_stop() -> None:
    """A stale ``_current_group_key`` snaps to the first stop on j."""
    agents = [
        _agent(project="p1", cl="cl1", name="a1"),
        _agent(project="p2", cl="cl2", name="b1"),
        _agent(project="p3", cl="cl3", name="c1"),
    ]
    app = _StubApp(
        agents,
        collapsed=[("p1", "cl1"), ("p2", "cl2"), ("p3", "cl3")],
    )
    app._current_group_key = ("ghost",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1")


def test_jk_at_l0_banner_moves_highlight_to_l1_banner() -> None:
    """When stepping from a collapsed L0 banner to a collapsed sibling
    L1 banner, the AgentList's rendered highlight tracks the new
    ``_current_group_key`` via ``update_highlight``.
    """
    from sase.ace.tui.widgets.agent_list import AgentList

    agents = [
        _agent(project="p1", cl="cl1", name="sase-r.first"),
        _agent(project="p1", cl="cl1", name="sase-r.second"),
        _agent(project="p1", cl="cl1", name="sase-q.first"),
        _agent(project="p1", cl="cl1", name="sase-q.second"),
    ]
    # Collapse the L0 *and* both L1s so every banner is selectable.
    app = _StubApp(
        agents,
        collapsed=[
            ("p1", "cl1"),
            ("p1", "cl1", "sase-q"),
            ("p1", "cl1", "sase-r"),
        ],
    )
    app._current_group_key = ("p1", "cl1")  # L0 project banner

    widget = AgentList()
    widget.update_list(
        agents,
        current_idx=0,
        fold_registry=app._group_fold_registry,
        current_group_key=app._current_group_key,
    )
    # When the L0 is collapsed we only render the L0 banner — its
    # children are hidden, so the highlight is row 0.
    assert widget.highlighted == 0

    # Expand the L0 so the L1 banners become visible & selectable.
    app._group_fold_registry.expand(("p1", "cl1"))
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("p1", "cl1", "sase-q")

    widget.update_list(
        agents,
        current_idx=app.current_idx,
        fold_registry=app._group_fold_registry,
        current_group_key=app._current_group_key,
    )
    widget.update_highlight(app.current_idx, None, group_key=app._current_group_key)
    # Highlight tracks the L1 banner row.
    assert widget.highlighted is not None
