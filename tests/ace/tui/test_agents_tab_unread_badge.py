"""Agents-tab unread badge wiring tests.

Covers ``_refresh_agents_tab_unread_badge`` on ``AgentsMixinCore`` and
the off-tab finalizer pipeline using a fake ``TabBar`` so tests run
without mounting a real Textual app.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
    compute_visible_unread_completed_count,
)
from sase.ace.tui.models.agent import Agent, AgentType

from ._agent_unread_helpers import make_agent


class _FakeTabBar:
    def __init__(self) -> None:
        self.badges: dict[str, int] = {"changespecs": 0, "agents": 0, "axe": 0}

    def set_tab_badge(self, tab: str, count: int) -> None:
        self.badges[tab] = max(count, 0)


class _BadgeApp(AgentsMixinCore):
    def __init__(
        self, agents: list[Agent], *, current_tab: str = "changespecs"
    ) -> None:
        self._agents = agents
        self.current_idx = 0
        self.current_tab = current_tab  # type: ignore[assignment]
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_display_status_by_identity: dict[
            tuple[AgentType, str, str | None], str
        ] = {}
        self._w_tab_bar: Any = _FakeTabBar()
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)


def _badges(app: _BadgeApp) -> dict[str, int]:
    return app._w_tab_bar.badges


def test_compute_count_filters_workflow_children() -> None:
    parent = make_agent(name="parent", status="DONE", raw_suffix="parent")
    child = make_agent(name="child", status="DONE", raw_suffix="parent/step", tag=None)
    object.__setattr__(child, "parent_workflow", "wf")
    object.__setattr__(child, "parent_timestamp", "parent")
    object.__setattr__(child, "step_name", "step")
    app = _BadgeApp([parent, child])
    app._unread_completed_agent_ids.update({parent.identity, child.identity})

    assert compute_visible_unread_completed_count(app) == 1  # type: ignore[arg-type]


def test_compute_count_ignores_stale_unread_identities() -> None:
    visible = make_agent(name="visible", status="DONE", raw_suffix="visible")
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    app = _BadgeApp([visible])
    app._unread_completed_agent_ids.update({visible.identity, stale.identity})

    assert compute_visible_unread_completed_count(app) == 1  # type: ignore[arg-type]


def test_off_tab_finalizer_marks_first_seen_and_updates_badge() -> None:
    a = make_agent(name="a", status="DONE", raw_suffix="a")
    b = make_agent(name="b", status="DONE", raw_suffix="b")
    app = _BadgeApp([a, b], current_tab="changespecs")

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]
    app._refresh_agents_tab_unread_badge()

    assert app._unread_completed_agent_ids == {a.identity, b.identity}
    assert _badges(app)["agents"] == 2


def test_switch_to_agents_tab_clears_badge_without_clearing_row_unread() -> None:
    a = make_agent(name="a", status="DONE", raw_suffix="a")
    app = _BadgeApp([a], current_tab="changespecs")
    app._unread_completed_agent_ids.add(a.identity)
    app._refresh_agents_tab_unread_badge()
    assert _badges(app)["agents"] == 1

    app.current_tab = "agents"  # type: ignore[assignment]
    app._refresh_agents_tab_unread_badge()

    assert _badges(app)["agents"] == 0
    # Row-level unread is untouched; it's the Agents-tab finalize pipeline
    # that reconciles selected/focused row acknowledgment.
    assert app._unread_completed_agent_ids == {a.identity}


def test_clear_agent_unread_refreshes_badge() -> None:
    a = make_agent(name="a", status="DONE", raw_suffix="a")
    b = make_agent(name="b", status="DONE", raw_suffix="b")
    app = _BadgeApp([a, b], current_tab="changespecs")
    app._unread_completed_agent_ids.update({a.identity, b.identity})
    app._refresh_agents_tab_unread_badge()
    assert _badges(app)["agents"] == 2

    app._clear_agent_unread(a)

    assert _badges(app)["agents"] == 1


def test_toggle_unread_refreshes_badge_off_tab() -> None:
    a = make_agent(name="a", status="DONE", raw_suffix="a")
    app = _BadgeApp([a], current_tab="agents")
    app.current_idx = 0
    # On the Agents tab the badge is always zero regardless of count.
    app._refresh_agents_tab_unread_badge()
    assert _badges(app)["agents"] == 0

    app._toggle_agent_unread()

    assert a.identity in app._manual_unread_agent_ids
    assert a.identity in app._unread_completed_agent_ids
    # Active Agents tab still suppresses the badge.
    assert _badges(app)["agents"] == 0


def test_badge_excludes_workflow_children_in_count() -> None:
    parent = make_agent(name="parent", status="DONE", raw_suffix="parent")
    child = make_agent(name="child", status="DONE", raw_suffix="parent/step")
    object.__setattr__(child, "parent_workflow", "wf")
    object.__setattr__(child, "parent_timestamp", "parent")
    object.__setattr__(child, "step_name", "step")
    app = _BadgeApp([parent, child], current_tab="changespecs")
    app._unread_completed_agent_ids.update({parent.identity, child.identity})
    app._refresh_agents_tab_unread_badge()

    assert _badges(app)["agents"] == 1


def test_badge_without_tab_bar_is_noop() -> None:
    a = make_agent(name="a", status="DONE", raw_suffix="a")
    app = _BadgeApp([a], current_tab="changespecs")
    app._w_tab_bar = None
    app._unread_completed_agent_ids.add(a.identity)
    # Should not raise.
    app._refresh_agents_tab_unread_badge()
