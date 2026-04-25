"""Tests for j/k navigation across banner rows on the Agents tab.

When the global group fold collapses agents (level < 3) the Agents
panel renders only banner rows.  The keyboard `j`/`k` bindings must
walk those banners in tree order, updating ``_current_group_key`` so
the rendered highlight follows.  At level 3 the original flat-agent
behavior must still hold.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldState


class _StubApp(BasicNavigationMixin):
    """Minimal harness exercising ``_navigate_agents_panel`` in isolation."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        level: int = 3,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._group_fold_state = AgentGroupFoldState(level=level)
        self._current_group_key: tuple[str, ...] | None = None

    def _agents_visible_order(self) -> list[int]:
        """Mirror :meth:`AgentsMixinCore._agents_visible_order` for tests."""
        from sase.ace.tui.models.agent_groups import build_agent_tree

        tree = build_agent_tree(self._agents, group_fold_level=3)
        return [
            entry.agent_idx
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


def _l0_roster() -> list[Agent]:
    """Three tag banners: 'alpha', 'beta', 'gamma' (one agent each)."""
    return [
        _agent(tag="alpha", name="a1"),
        _agent(tag="beta", name="b1"),
        _agent(tag="gamma", name="c1"),
    ]


def test_l0_j_cycles_through_tag_banners() -> None:
    app = _StubApp(_l0_roster(), level=0)
    # Pre-position on the first banner so the first `j` advances.
    app._current_group_key = ("alpha",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("beta",)
    assert app.current_idx == 1
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("gamma",)
    assert app.current_idx == 2
    # Wraps to first.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha",)
    assert app.current_idx == 0


def test_l0_k_reverses_tag_banner_cycle() -> None:
    app = _StubApp(_l0_roster(), level=0)
    app._current_group_key = ("alpha",)

    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("gamma",)
    assert app.current_idx == 2
    app._navigate_agents_panel(-1)
    assert app._current_group_key == ("beta",)
    assert app.current_idx == 1


def test_l1_cycles_project_banners() -> None:
    """One banner per (tag, project, cl) tuple plus the tag header above."""
    agents = [
        _agent(tag="alpha", project="p1", cl="cl1", name="a"),
        _agent(tag="alpha", project="p2", cl="cl2", name="b"),
        _agent(tag="alpha", project="p3", cl="cl3", name="c"),
    ]
    app = _StubApp(agents, level=1)
    # Walk the four-row banner sequence in tree order.
    app._current_group_key = ("alpha",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha", "p1", "cl1")
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha", "p2", "cl2")
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha", "p3", "cl3")
    # Wraps back to the tag header.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha",)


def test_l2_cycles_all_six_banners() -> None:
    """L2 fold: tag + project + name-root banners all visible.

    Each name-root has two entries — singletons would be suppressed at
    level 2, so duplicating per root keeps every banner in the cycle.
    """
    agents = [
        _agent(tag="alpha", project="p1", cl="cl1", name="d.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="d.second"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-r.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-r.second"),
        _agent(tag="alpha", project="p1", cl="cl1", name="j.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="j.second"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-q.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-q.second"),
    ]
    app = _StubApp(agents, level=2)
    app._current_group_key = ("alpha",)

    keys: list[tuple[str, ...] | None] = []
    # Six steps through the row sequence; final step wraps.
    for _ in range(6):
        app._navigate_agents_panel(1)
        keys.append(app._current_group_key)
    # Name-root banners render in deterministic alpha order within the project.
    assert keys == [
        ("alpha", "p1", "cl1"),
        ("alpha", "p1", "cl1", "d"),
        ("alpha", "p1", "cl1", "j"),
        ("alpha", "p1", "cl1", "sase-q"),
        ("alpha", "p1", "cl1", "sase-r"),
        ("alpha",),  # wrap to start
    ]


def test_l3_keeps_flat_agent_navigation() -> None:
    """Regression guard: at level 3 j/k must still cycle agents.

    Input is already in tag-alphabetical order, so visible order ==
    input order and the cursor walks 0 -> 1 -> 2 -> 0.
    """
    agents = _l0_roster()
    app = _StubApp(agents, level=3, current_idx=0)
    app._current_group_key = ("stale",)

    app._navigate_agents_panel(1)
    assert app.current_idx == 1
    assert app._current_group_key is None
    app._navigate_agents_panel(1)
    assert app.current_idx == 2
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap


def test_l3_walks_visible_grouping_order_not_input_order() -> None:
    """Regression for agents_jk_random_jumps_at_fold_3.

    Agents in scrambled tag order: input ``[zeta, alpha, beta]`` renders
    as ``[alpha, beta, zeta]`` after the level-3 grouping walk.  j from
    the visually-first row (``alpha``, global idx 1) must advance to
    ``beta`` (idx 2), then ``zeta`` (idx 0), then wrap.
    """
    agents = [
        _agent(tag="zeta", name="z1"),
        _agent(tag="alpha", name="a1"),
        _agent(tag="beta", name="b1"),
    ]
    app = _StubApp(agents, level=3, current_idx=1)  # alpha — visually first

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # beta
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # zeta
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # wrap to alpha


def test_l3_k_walks_visible_grouping_order_in_reverse() -> None:
    """Symmetric reverse walk for the scrambled-tag case."""
    agents = [
        _agent(tag="zeta", name="z1"),
        _agent(tag="alpha", name="a1"),
        _agent(tag="beta", name="b1"),
    ]
    app = _StubApp(agents, level=3, current_idx=1)  # alpha — visually first

    app._navigate_agents_panel(-1)
    assert app.current_idx == 0  # wraps backward to zeta (visually last)
    app._navigate_agents_panel(-1)
    assert app.current_idx == 2  # beta
    app._navigate_agents_panel(-1)
    assert app.current_idx == 1  # alpha


def test_l3_interleaved_untagged_walk_keeps_block_contiguous() -> None:
    """Mirrors the user's interleaved-tag report.

    Input order ``[(untagged), (untagged), @name_level, (untagged)]``
    must render with all three ``(untagged)`` agents contiguous, then
    the ``@name_level`` agent.  Since ``(untagged)`` sorts after named
    tags, the visible order is
    ``[name_level (idx 2), untagged_a (0), untagged_b (1), untagged_c (3)]``.
    Walking ``j`` from the first ``(untagged)`` must visit the second
    and third ``(untagged)``s before the ``name_level`` agent — never
    ping-pong across the banner boundary.
    """
    agents = [
        _agent(tag="", name="u1"),  # 0 untagged
        _agent(tag="", name="u2"),  # 1 untagged
        _agent(tag="name_level", name="nl"),  # 2 named tag
        _agent(tag="", name="u3"),  # 3 untagged
    ]
    app = _StubApp(agents, level=3, current_idx=0)  # first untagged

    # Visible order: [2 (name_level), 0, 1, 3].  Starting at idx 0
    # (visually second), j -> 1 -> 3 -> 2 -> 0.
    app._navigate_agents_panel(1)
    assert app.current_idx == 1
    app._navigate_agents_panel(1)
    assert app.current_idx == 3
    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # crosses to name_level after all untagged
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap


def test_l3_workflow_children_inherit_parent_grouping_in_walk() -> None:
    """Workflow children render contiguous with their parent.

    Input ``[parent (tagA), unrelated (tagB), child_of_parent]``: the
    child inherits ``tagA`` from its parent so the visible order is
    ``[parent, child, unrelated]``.  Pressing ``j`` from the parent must
    land on the workflow child, not the unrelated agent.
    """
    parent = _agent(tag="alpha", name="parent")
    parent.raw_suffix = "ts_parent"
    unrelated = _agent(tag="zeta", name="unrelated")
    child = _agent(tag="", name="parent.step1")
    child.parent_timestamp = "ts_parent"
    child.parent_workflow = "wf"
    agents = [parent, unrelated, child]

    app = _StubApp(agents, level=3, current_idx=0)  # parent

    app._navigate_agents_panel(1)
    assert app.current_idx == 2  # workflow child (visually contiguous)
    app._navigate_agents_panel(1)
    assert app.current_idx == 1  # unrelated
    app._navigate_agents_panel(1)
    assert app.current_idx == 0  # wrap to parent


def test_unmatched_group_key_lands_on_first_banner() -> None:
    """If ``_current_group_key`` matches no visible banner, snap to first."""
    app = _StubApp(_l0_roster(), level=0)
    app._current_group_key = ("ghost",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha",)
    assert app.current_idx == 0


def test_jk_at_l1_banner_moves_visible_highlight_to_l2_banner() -> None:
    """Regression for jk_banner_highlight: at fold level 2, advancing from
    an L1 (project) banner to the L2 (name-root) banner must move the
    AgentList's rendered highlight, not just ``_current_group_key``.

    Reproduces the user's snapshot: cursor on `── sase / sase ──`, press
    `j`, expect highlight to land on `· sase-r ·` rather than visually
    sticking on the L1 banner.
    """
    from sase.ace.tui.widgets.agent_list import AgentList

    agents = [
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-r.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-r.second"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-q.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-q.second"),
    ]
    app = _StubApp(agents, level=2)
    app._current_group_key = ("alpha", "p1", "cl1")  # L1 project banner

    widget = AgentList()
    widget.update_list(
        agents,
        current_idx=0,
        group_fold_level=2,
        current_group_key=app._current_group_key,
    )
    # Layout at L2: tag (0), project (1), name-root sase-q (2),
    # name-root sase-r (3).  Starts highlighted on the project banner.
    assert widget.highlighted == 1

    # Drive the action-level navigation: j moves to the next banner in
    # tree order — the first L2 name-root.
    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha", "p1", "cl1", "sase-q")

    # The debounced refresh path then calls update_highlight with the
    # new group_key.  Before the fix this left the highlight on the L1
    # banner; after the fix it advances to the L2 banner row.
    local_idx = app.current_idx
    widget.update_highlight(local_idx, None, group_key=app._current_group_key)
    assert widget.highlighted == 2
