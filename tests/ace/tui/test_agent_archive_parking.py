"""Parking round trips, FilterBar cancel, and Archive import deferral."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.grouping_strategy import (
    load_agent_archive_grouping,
    save_agent_archive_grouping,
)
from sase.ace.tui.actions.agents._archive_view import (
    close_agents_archive_view,
    flush_pending_archive_list_scroll,
    init_agents_archive_view_state,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_DEFAULT_GROUPING,
    ARCHIVE_DEFAULT_QUERY,
)
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.feature_flags import override_flags


def _make_agent(cl_name: str, *, tribe: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        tribe=tribe,
    )


class _FoldRegistry:
    def __init__(self, folds: tuple[str, ...] = ()) -> None:
        self._folds = folds

    def snapshot(self) -> tuple[str, ...]:
        return self._folds

    def restore(self, folds: tuple[str, ...]) -> None:
        self._folds = tuple(folds)


class _FakeScroller:
    def __init__(self, scroll_y: float = 0.0) -> None:
        self.scroll_y = scroll_y


class _FakePanel:
    def __init__(
        self,
        deck: DeckId,
        *,
        preferred_cards: dict[DeckId, str] | None = None,
        scroll_y: float = 0.0,
    ) -> None:
        self.deck = deck
        self.preferred_cards = dict(preferred_cards or {})
        self.preferred_card = self.preferred_cards.get(DeckId.MAIN)
        self._scroll = _FakeScroller(scroll_y)

    def active_scroll(self) -> _FakeScroller:
        return self._scroll


class _FakeDeckArea:
    def __init__(self, panels: dict[int, _FakePanel]) -> None:
        self.state = SimpleNamespace(panels=panels)

    def panel(self, pane_id: int) -> _FakePanel:
        return self.state.panels[pane_id]

    def set_preferred_cards(self, pane_id: int, cards: dict[DeckId, str]) -> None:
        self.state.panels[pane_id].preferred_cards = dict(cards)
        self.state.panels[pane_id].preferred_card = dict(cards).get(DeckId.MAIN)


class _FakeDetail:
    def __init__(self, area: _FakeDeckArea) -> None:
        self.deck_area = area
        self.shown: list[tuple[int, DeckId]] = []

    def show_deck(self, pane_id: int, deck: DeckId) -> None:
        self.shown.append((pane_id, deck))
        self.deck_area.state.panels[pane_id].deck = deck


class _FakeArchiveList:
    def __init__(self) -> None:
        self.scroll_y = 0
        self.max_scroll_y = 80


class _ParkingApp:
    """Drive open/close against a fake live deck area keyed by pane id."""

    def __init__(self) -> None:
        self._agents = [
            _make_agent("agent_0"),
            _make_agent("agent_1", tribe="alpha"),
        ]
        self._agent_search_query = "model:opus"
        self.current_idx = 1
        self.current_tab = "agents"
        self._active_agent_tab = "running"
        self._current_group_key = ("status", "RUNNING")
        self._agent_panels_grouped = True
        self._expanded_panel_focus = False
        self._collapsed_panel_keys: set[str] = set()
        self._expanded_panel_keys: set[str] = set()
        self._agents_filter_session_open = False
        self._panel_group = AgentPanelGroup.from_agents(self._agents)
        self._panel_group.focused_idx = 0
        self._group_fold_registry = _FoldRegistry(("banner:today",))
        self.applied_snapshots: list[Any] = []
        self.filter_closes = 0
        self.refilters = 0
        self._after_refresh: list[Any] = []
        self._pending_archive_list_scroll = 0
        self._detail = _FakeDetail(
            _FakeDeckArea(
                {
                    1: _FakePanel(
                        DeckId.FINAL, preferred_cards={DeckId.FINAL: "overview"}
                    ),
                    2: _FakePanel(
                        DeckId.MAIN,
                        preferred_cards={DeckId.MAIN: "prompt", DeckId.FILES: "diff"},
                    ),
                }
            )
        )
        self._archive_list = _FakeArchiveList()
        self._agent_list = SimpleNamespace(scroll_y=0.0)
        self._deck_snapshot = SimpleNamespace(
            layout="split",
            ratio=30,
            panels=[
                SimpleNamespace(
                    deck=DeckId.TOOLS,
                    preferred_cards={},
                    preferred_card="stale",
                )
            ],
        )
        init_agents_archive_view_state(self)

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _resolve_focused_panel(self) -> Any:
        return SimpleNamespace(panel_key="alpha")

    def _capture_agents_deck_state(self) -> Any:
        return self._deck_snapshot

    def _apply_agents_deck_snapshot(self, snapshot: Any) -> bool:
        self.applied_snapshots.append(snapshot)
        return True

    def _close_agents_filter_session(self) -> None:
        self.filter_closes += 1
        self._agents_filter_session_open = False

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self.refilters += 1

    def call_after_refresh(self, callback: Any) -> None:
        self._after_refresh.append(callback)

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-detail-panel":
            return self._detail
        if selector == "#archive-list":
            return self._archive_list
        if selector == "#agent-list-panel":
            return self._agent_list
        raise LookupError(selector)


def test_return_restores_deck_and_card_without_reapplying_splits() -> None:
    app = _ParkingApp()

    open_agents_archive_view(app)
    app._detail.deck_area.state.panels[1].deck = DeckId.MAIN
    app._detail.deck_area.state.panels[1].preferred_cards = {DeckId.MAIN: "chat"}
    app._detail.shown.clear()
    close_agents_archive_view(app)

    assert app.applied_snapshots == []
    assert (1, DeckId.FINAL) in app._detail.shown
    assert app._detail.deck_area.state.panels[1].deck is DeckId.FINAL
    assert app._detail.deck_area.state.panels[1].preferred_cards[DeckId.FINAL] == (
        "overview"
    )
    assert app._detail.deck_area.state.panels[2].preferred_cards[DeckId.FILES] == "diff"
    assert app._agent_search_query == "model:opus"
    assert app.current_idx == 1
    assert app._active_agent_tab == "running"
    assert app._current_group_key == ("status", "RUNNING")
    assert app._agent_panels_grouped is True
    assert app._group_fold_registry.snapshot() == ("banner:today",)
    assert app._panel_group.focused_idx == app._panel_group.panel_keys.index("alpha")
    assert app._expanded_panel_focus is True


def test_archive_parks_per_panel_deck_card_and_scroll_across_reentry() -> None:
    app = _ParkingApp()

    open_agents_archive_view(app)
    assert app._agents_archive_view.archive.deck_choices == {}
    app._detail.deck_area.state.panels[2].deck = DeckId.TOOLS
    app._detail.deck_area.state.panels[2].preferred_cards = {
        DeckId.TOOLS: "calls",
        DeckId.MAIN: "prompt",
    }
    app._detail.deck_area.panel(1).active_scroll().scroll_y = 12.0
    close_agents_archive_view(app)
    parked = app._agents_archive_view.archive.deck_choices
    assert parked["2"] == "tools"
    assert parked["2:card:tools"] == "calls"
    assert parked["2:card:main"] == "prompt"
    assert parked["1:scroll"] == "12.0"
    app._detail.shown.clear()
    open_agents_archive_view(app)

    assert (2, DeckId.TOOLS) in app._detail.shown
    assert (
        app._detail.deck_area.state.panels[2].preferred_cards[DeckId.TOOLS] == "calls"
    )
    assert app._detail.deck_area.panel(1).active_scroll().scroll_y == 12.0


def test_reading_order_snapshot_without_pane_ids_is_ignored() -> None:
    app = _ParkingApp()
    app._detail = None  # type: ignore[assignment]

    def _missing_detail(selector: str, _type: Any = None) -> Any:
        if selector == "#agent-detail-panel":
            raise LookupError(selector)
        if selector == "#archive-list":
            return app._archive_list
        if selector == "#agent-list-panel":
            return app._agent_list
        raise LookupError(selector)

    app.query_one = _missing_detail  # type: ignore[method-assign]

    open_agents_archive_view(app)
    parked = app._agents_archive_view.parked_inbox
    assert parked is not None
    assert parked.deck_choices == {}


def test_collapsed_ungrouped_panel_restores_collapsed_focus() -> None:
    app = _ParkingApp()
    app._agent_panels_grouped = False
    app._collapsed_panel_keys = {"alpha"}

    open_agents_archive_view(app)
    close_agents_archive_view(app)

    assert app._expanded_panel_focus is False


def test_archive_list_scroll_restores_after_rows_exist() -> None:
    app = _ParkingApp()
    app._archive_list.scroll_y = 40

    open_agents_archive_view(app)
    close_agents_archive_view(app)
    app._archive_list.scroll_y = 0
    app._archive_list.max_scroll_y = 25
    app._after_refresh.clear()
    open_agents_archive_view(app)
    assert app._archive_list.scroll_y == 0
    flush_pending_archive_list_scroll(app)
    assert app._after_refresh
    app._after_refresh[-1]()

    assert app._archive_list.scroll_y == 25


def test_open_and_pulse_return_close_an_open_filter_session() -> None:
    app = _ParkingApp()
    app._agents_filter_session_open = True

    open_agents_archive_view(app)
    assert app.filter_closes == 1
    assert app._agents_filter_session_open is False
    assert app.refilters >= 1

    app._agents_filter_session_open = True
    close_agents_archive_view(app)
    assert app.filter_closes == 2
    assert app._agents_filter_session_open is False

    app._agents_filter_session_open = True
    open_agents_archive_view_with_query(app, query="in:archive outcome:failed")
    assert app.filter_closes == 3
    assert app._agents_archive_view.archive.committed_query == (
        "in:archive outcome:failed"
    )


def test_clearing_name_inside_archive_keeps_selected_identity() -> None:
    app = _ParkingApp()
    open_agents_archive_view_with_query(app, query='in:archive name:"worker"')
    app._agents_archive_view.archive.selected_key = "worker"
    app._agents_archive_view.archive.reveal_row = {"name": "worker"}

    open_agents_archive_view_with_query(app, query="in:archive")

    archive = app._agents_archive_view.archive
    assert archive.committed_query == "in:archive"
    assert archive.selected_key == "worker"
    assert archive.reveal_row == {"name": "worker"}


def test_new_exact_arrival_takes_over_archive_selection() -> None:
    app = _ParkingApp()
    open_agents_archive_view_with_query(app, query='in:archive name:"worker"')
    app._agents_archive_view.archive.selected_key = "worker"
    app._agents_archive_view.archive.reveal_row = {"name": "worker"}

    open_agents_archive_view_with_query(
        app, query='in:archive name:"other"', agent_name="other"
    )

    archive = app._agents_archive_view.archive
    assert archive.selected_key is None
    assert archive.reveal_row is None
    assert archive.pending_exact_name == "other"


def test_default_panel_focus_encodes_as_empty_string() -> None:
    app = _ParkingApp()

    open_agents_archive_view(app)
    parked = app._agents_archive_view.parked_inbox
    assert parked is not None
    assert parked.focused_panel == "alpha"
    assert parked.panel_layout is True

    app._resolve_focused_panel = lambda: SimpleNamespace(panel_key=None)
    close_agents_archive_view(app)
    open_agents_archive_view(app)
    parked = app._agents_archive_view.parked_inbox
    assert parked is not None
    assert parked.focused_panel == ""


async def test_quitting_from_archive_persists_grouping_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "agent_archive_grouping.txt"
    monkeypatch.setattr(
        "sase.ace.grouping_strategy._agent_archive_grouping_path",
        lambda: path,
    )
    save_agent_archive_grouping("project")
    app = _ParkingApp()

    async def _settle_archive_tasks() -> None:
        while tasks := tuple(app._archive_controller_tasks):
            await asyncio.gather(*tasks, return_exceptions=True)

    open_agents_archive_view(app)
    await _settle_archive_tasks()
    app._agents_archive_view.archive.selected_key = "alice@run"
    app._agents_archive_view.archive.deck_choices = {"0": "final"}
    app._agents_archive_view.archive.committed_query = "in:archive status:failed"
    init_agents_archive_view_state(app)
    state = app._agents_archive_view
    assert state.active_view == AGENTS_VIEW_INBOX
    assert state.parked_inbox is None
    assert state.archive.grouping == ARCHIVE_DEFAULT_GROUPING
    assert state.archive.selected_key is None
    assert state.archive.deck_choices == {}
    assert state.archive.committed_query == ARCHIVE_DEFAULT_QUERY
    assert load_agent_archive_grouping() == "project"

    open_agents_archive_view(app)
    await _settle_archive_tasks()
    assert app._agents_archive_view.archive.grouping == "project"
