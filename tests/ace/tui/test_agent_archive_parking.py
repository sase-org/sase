"""Parking round trips, FilterBar cancel, and Archive import deferral."""

from __future__ import annotations

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
    init_agents_archive_view_state,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
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


class _ParkingApp:
    """Drive open/close without a composed widget tree."""

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
        self._agents_filter_session_open = False
        self._panel_group = AgentPanelGroup.from_agents(self._agents)
        self._panel_group.focused_idx = 0
        self._group_fold_registry = _FoldRegistry(("banner:today",))
        self.applied_snapshots: list[Any] = []
        self.restored_choices: list[dict[str, str]] = []
        self.filter_closes = 0
        self.refilters = 0
        self._deck_snapshot = SimpleNamespace(
            layout="split",
            ratio=30,
            panels=[
                SimpleNamespace(
                    deck=SimpleNamespace(value="final"),
                    preferred_cards={},
                    preferred_card="overview",
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

    def _restore_parked_deck_choices(self, choices: dict[str, str]) -> None:
        self.restored_choices.append(dict(choices))

    def _close_agents_filter_session(self) -> None:
        self.filter_closes += 1
        self._agents_filter_session_open = False

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self.refilters += 1

    def query_one(self, selector: str, _type: Any = None) -> Any:
        raise LookupError(selector)


def test_return_restores_deck_and_card_without_reapplying_splits() -> None:
    app = _ParkingApp()

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        app._deck_snapshot = SimpleNamespace(
            layout="triple",
            ratio=70,
            panels=[
                SimpleNamespace(
                    deck=SimpleNamespace(value="main"),
                    preferred_cards={},
                    preferred_card="prompt",
                )
            ],
        )
        close_agents_archive_view(app)

    assert app.applied_snapshots == []
    assert app.restored_choices[-1] == {"0": "final", "0:card": "overview"}
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

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        assert app._agents_archive_view.archive.deck_choices == {}
        app._deck_snapshot = SimpleNamespace(
            layout="split",
            ratio=45,
            panels=[
                SimpleNamespace(
                    deck=SimpleNamespace(value="runs"),
                    preferred_cards={},
                    preferred_card="live",
                )
            ],
        )
        close_agents_archive_view(app)
        parked = app._agents_archive_view.archive.deck_choices
        assert parked["0"] == "runs"
        assert parked["0:card"] == "live"
        app.restored_choices.clear()
        open_agents_archive_view(app)

    assert app.restored_choices[-1]["0"] == "runs"
    assert app.restored_choices[-1]["0:card"] == "live"


def test_open_and_pulse_return_close_an_open_filter_session() -> None:
    app = _ParkingApp()
    app._agents_filter_session_open = True

    with override_flags(agents_archive_view=True):
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


def test_default_panel_focus_encodes_as_empty_string() -> None:
    app = _ParkingApp()

    with override_flags(agents_archive_view=True):
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


def test_quitting_from_archive_persists_grouping_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "agent_archive_grouping.txt"
    monkeypatch.setattr(
        "sase.ace.grouping_strategy._agent_archive_grouping_path",
        lambda: path,
    )
    save_agent_archive_grouping("project")
    app = _ParkingApp()

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        app._agents_archive_view.archive.selected_key = "alice@run"
        app._agents_archive_view.archive.deck_choices = {"0": "final"}
        app._agents_archive_view.archive.committed_query = "in:archive status:failed"
        init_agents_archive_view_state(app)
        state = app._agents_archive_view
        assert state.active_view == AGENTS_VIEW_INBOX
        assert state.parked_inbox is None
        assert state.archive.grouping == "project"
        assert state.archive.selected_key is None
        assert state.archive.deck_choices == {}
        assert state.archive.committed_query == ARCHIVE_DEFAULT_QUERY
        assert load_agent_archive_grouping() == "project"
