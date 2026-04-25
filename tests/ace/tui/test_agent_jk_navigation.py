"""Tests for j/k navigation across banner rows on the Agents tab.

When the global group fold collapses agents (level < 3) the Agents
panel renders only banner rows.  The keyboard `j`/`k` bindings must
walk those banners in tree order, updating ``_current_group_key`` so
the rendered highlight follows.  At level 3 the original flat-agent
behavior must still hold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
        focused: Literal["main", "pinned"] = "main",
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._group_fold_state = AgentGroupFoldState(level=level)
        self._current_group_key: tuple[str, ...] | None = None
        self._pinned_panel_focused = focused
        # Treat every agent as belonging to the main panel so the flat
        # path remains stable when level == 3 or pinned panel focus.
        self._main_panel_indices = list(range(len(agents)))
        self._pinned_panel_indices: list[int] = []
        self._main_panel_idx_map = {i: i for i in range(len(agents))}
        self._pinned_panel_idx_map: dict[int, int] = {}

    def _active_panel_indices(self) -> list[int]:
        if self._pinned_panel_focused == "pinned":
            return self._pinned_panel_indices
        return self._main_panel_indices

    def _active_panel_idx_map(self) -> dict[int, int]:
        if self._pinned_panel_focused == "pinned":
            return self._pinned_panel_idx_map
        return self._main_panel_idx_map


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
    tags = (tag,) if tag else ()
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tags=tags,
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
    """L2 fold: tag + project + name-root banners all visible."""
    agents = [
        _agent(tag="alpha", project="p1", cl="cl1", name="d.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-r.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="j.first"),
        _agent(tag="alpha", project="p1", cl="cl1", name="sase-q.first"),
    ]
    app = _StubApp(agents, level=2)
    app._current_group_key = ("alpha",)

    keys: list[tuple[str, ...] | None] = []
    # Six steps through the row sequence; final step wraps.
    for _ in range(6):
        app._navigate_agents_panel(1)
        keys.append(app._current_group_key)
    assert keys == [
        ("alpha", "p1", "cl1"),
        ("alpha", "p1", "cl1", "d"),
        ("alpha", "p1", "cl1", "sase-r"),
        ("alpha", "p1", "cl1", "j"),
        ("alpha", "p1", "cl1", "sase-q"),
        ("alpha",),  # wrap to start
    ]


def test_l3_keeps_flat_agent_navigation() -> None:
    """Regression guard: at level 3 j/k must still cycle agents."""
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


def test_unmatched_group_key_lands_on_first_banner() -> None:
    """If ``_current_group_key`` matches no visible banner, snap to first."""
    app = _StubApp(_l0_roster(), level=0)
    app._current_group_key = ("ghost",)

    app._navigate_agents_panel(1)
    assert app._current_group_key == ("alpha",)
    assert app.current_idx == 0


def test_pinned_panel_skips_banner_cycle() -> None:
    """On the pinned panel j/k stays flat even when group level < 3."""
    agents = _l0_roster()
    app = _StubApp(agents, level=0, focused="pinned")
    # Route all three agents into the pinned panel.
    app._pinned_panel_indices = [0, 1, 2]
    app._pinned_panel_idx_map = {0: 0, 1: 1, 2: 2}

    app._navigate_agents_panel(1)
    assert app.current_idx == 1
    assert app._current_group_key is None
    app._navigate_agents_panel(1)
    assert app.current_idx == 2
    app._navigate_agents_panel(1)
    assert app.current_idx == 0
