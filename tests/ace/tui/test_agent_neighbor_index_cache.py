"""Integration tests for the cached Agents-tab neighbor index."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import RunnerCapacitySnapshot
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_hoods import AgentNeighborRow
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(
    name: str,
    *,
    suffix: str,
    tribe: str | None = None,
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/r/proj/proj.sase",
        status=status,
        start_time=datetime(2026, 5, 23, 12, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        tribe=tribe,
    )


class _Bare(AgentDisplayMixin):
    def __init__(self, agents: list[Agent], *, grouped: bool = False) -> None:
        self._agents = agents
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self._agent_neighbor_index_cache = None
        self._dismiss_revive_epoch = 0
        self._panel_group = AgentPanelGroup.from_agents(
            agents, merge_tribe_panels=grouped
        )
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = grouped
        self._marked_agents = set()
        self._fold_counts = {}
        self._dismissed_agents = set()
        self._dismissed_agent_objects: list[Agent] = []
        self.current_idx = 0
        self.current_attempt_number = None
        self._current_group_key = None
        self._agent_search_query = ""
        self._unread_completed_agent_ids = set()
        self._countdown_remaining = 0
        self.refresh_interval = 0
        self.visible_walk_count = 0

    def _visible_agent_neighbor_rows(self) -> Iterator[AgentNeighborRow]:
        self.visible_walk_count += 1
        yield from super()._visible_agent_neighbor_rows()

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def test_agent_neighbor_index_is_cached_for_repeated_count_reads() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("foo.code", suffix="b"),
            _agent("foo.review", suffix="c"),
        ]
    )

    assert app._agent_neighbor_index().neighbor_count(0) == 2
    for _ in range(25):
        assert app._agent_neighbor_index().neighbor_count(1) == 2

    assert app.visible_walk_count == 1


def test_agent_neighbor_index_cache_clears_with_panel_cache_invalidation() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("foo.code", suffix="b"),
        ]
    )

    first = app._agent_neighbor_index()
    app._invalidate_agent_panel_cache()
    second = app._agent_neighbor_index()

    assert second is not first
    assert app.visible_walk_count == 2


def test_agent_neighbor_index_cache_tracks_fold_version() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("foo.code", suffix="b"),
            _agent("bar.plan", suffix="c"),
        ]
    )
    assert app._agent_neighbor_index().neighbor_count(0) == 1

    app._group_fold_registry.collapse(("proj", "demo", "foo"))

    assert app._agent_neighbor_index().neighbor_count(0) == 0
    assert app.visible_walk_count == 2


def test_agent_neighbor_index_walks_panels_in_render_order() -> None:
    app = _Bare(
        [
            _agent("foo.zeta", suffix="z", tribe="zeta"),
            _agent("foo.alpha", suffix="a", tribe="alpha"),
            _agent("foo.no_tribe", suffix="u", tribe=None),
        ]
    )

    index = app._agent_neighbor_index()

    assert app._panel_group.panel_keys == [None, "alpha", "zeta"]
    assert index.neighbors_for(2) == (1, 0)
    assert index.neighbors_for(1) == (2, 0)
    assert index.panel_idx_for(2) == 0
    assert index.panel_idx_for(1) == 1
    assert index.panel_idx_for(0) == 2


def test_agent_neighbor_index_omits_starting_rows_from_app_walk() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("foo.starting", suffix="starting", status="STARTING"),
            _agent("foo.code", suffix="b"),
        ]
    )

    index = app._agent_neighbor_index()

    assert index.neighbors_for(0) == (2,)
    assert index.neighbors_for(1) == ()
    assert index.neighbors_for(2) == (0,)


def test_agent_neighbor_index_cache_tracks_panel_mode() -> None:
    app = _Bare(
        [
            _agent("foo.alpha", suffix="a", tribe="alpha"),
            _agent("foo.beta", suffix="b", tribe="beta"),
        ]
    )
    split = app._agent_neighbor_index()

    app._agent_panels_grouped = True
    app._panel_group = AgentPanelGroup.from_agents(app._agents, merge_tribe_panels=True)

    grouped = app._agent_neighbor_index()

    assert grouped is not split
    assert grouped.panel_idx_for(0) == 0
    assert grouped.panel_idx_for(1) == 0
    assert app.visible_walk_count == 2


def test_agent_neighbor_index_cache_tracks_dismiss_revive_epoch() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("bar.plan", suffix="b"),
        ]
    )
    dismissed = _agent("foo.plan.child", suffix="d")
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}

    first = app._agent_neighbor_index()
    assert first.descendant_count(0) == 1

    dismissed_2 = _agent("foo.plan.child2", suffix="e")
    app._dismissed_agent_objects.append(dismissed_2)
    app._dismissed_agents.add(dismissed_2.identity)
    changed_membership = app._agent_neighbor_index()
    assert changed_membership is not first
    assert changed_membership.descendant_count(0) == 2

    app._dismiss_revive_epoch += 1
    second = app._agent_neighbor_index()

    assert second is not changed_membership
    assert second.descendant_count(0) == 2
    assert app.visible_walk_count == 3


def test_agents_info_panel_update_uses_cached_neighbor_count() -> None:
    app = _Bare(
        [
            _agent("foo.plan", suffix="a"),
            _agent("foo.code", suffix="b"),
            _agent("foo.review", suffix="c"),
        ]
    )
    app._agent_runner_capacity = RunnerCapacitySnapshot(10, 3, 2)

    class _InfoPanel:
        kwargs: dict[str, Any]

        def update_state(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _DetailPanel:
        panel_mode_label = ""

    info_panel = _InfoPanel()
    detail_panel = _DetailPanel()

    def _query_one(selector: str, _type: Any = None) -> Any:
        if selector == "#agent-info-panel":
            return info_panel
        if selector == "#agent-detail-panel":
            return detail_panel
        raise AssertionError(selector)

    app.query_one = _query_one  # type: ignore[attr-defined]

    app._update_agents_info_panel()
    app._update_agents_info_panel()

    assert info_panel.kwargs["neighbor_count"] == 2
    assert info_panel.kwargs["runner_limit"] == 10
    assert info_panel.kwargs["runner_slots_in_use"] == 3
    assert info_panel.kwargs["runner_queue_count"] == 2
    assert app.visible_walk_count == 1
