"""Lifecycle and race tests for Agents-tab deck-layout persistence."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from sase.ace.tui.actions.agents._deck_persistence import AgentDeckPersistenceMixin
from sase.ace.tui.models.agent_deck_persistence import (
    AgentsDeckStateSnapshot,
    area_state_from_snapshot,
    snapshot_from_area_state,
)
from sase.ace.tui.widgets.decks.layout import toggle_split
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)


def _split_snapshot() -> AgentsDeckStateSnapshot:
    state = toggle_split(
        DeckAreaState(), DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.FILES)
    )
    return snapshot_from_area_state(state)


class _Harness(AgentDeckPersistenceMixin):
    def __init__(self) -> None:
        self._deck_area_state = DeckAreaState()
        self.applied: list[AgentsDeckStateSnapshot] = []
        self._ensure_agents_deck_persistence_state()

    def _capture_agents_deck_state(self) -> AgentsDeckStateSnapshot | None:
        return snapshot_from_area_state(self._deck_area_state)

    def _apply_agents_deck_snapshot(self, snapshot: AgentsDeckStateSnapshot) -> bool:
        self.applied.append(snapshot)
        self._deck_area_state = area_state_from_snapshot(snapshot)
        return True


def test_pre_load_change_wins_over_disk_baseline() -> None:
    app = _Harness()
    app._deck_area_state = toggle_split(
        app._deck_area_state,
        DeckLayout.TOP_BOTTOM,
        DeckPanelState(DeckId.TOOLS),
    )
    app._agents_deck_state_changed()

    app._resolve_agents_deck_state_load(AgentsDeckStateSnapshot())

    assert app._agents_deck_state_merged is True
    # Disk baseline applied first, then the newer pre-load user intent.
    assert [s.layout for s in app.applied] == [
        DeckLayout.SINGLE,
        DeckLayout.TOP_BOTTOM,
    ]
    assert app._deck_area_state.layout is DeckLayout.TOP_BOTTOM
    assert app._deck_area_state.panels[1].deck is DeckId.TOOLS
    # The winning intent is queued for save.
    assert app._agents_deck_state_save_generation == 1
    generation, pending = app._agents_deck_state_save_pending or (None, None)
    assert generation == 1
    assert pending is not None and pending.layout is DeckLayout.TOP_BOTTOM


def test_unchanged_notify_schedules_no_save() -> None:
    app = _Harness()
    app._agents_deck_state_merged = True
    app._agents_deck_state_last_snapshot = snapshot_from_area_state(
        app._deck_area_state
    )

    app._agents_deck_state_changed()

    assert app._agents_deck_state_save_generation == 0
    assert app._agents_deck_state_save_pending is None


@pytest.mark.asyncio
async def test_rapid_mutations_coalesce_to_latest_generation() -> None:
    app = _Harness()
    app._agents_deck_state_merged = True
    app._agents_deck_state_last_snapshot = snapshot_from_area_state(
        app._deck_area_state
    )
    started = threading.Event()
    release = threading.Event()
    saved: list[AgentsDeckStateSnapshot] = []

    def _save(snapshot: AgentsDeckStateSnapshot) -> None:
        saved.append(snapshot)
        if len(saved) == 1:
            started.set()
            release.wait(timeout=2)

    app._save_agents_deck_state_now = _save  # type: ignore[method-assign]
    app._deck_area_state = toggle_split(
        app._deck_area_state,
        DeckLayout.LEFT_RIGHT,
        DeckPanelState(DeckId.FILES),
    )
    app._agents_deck_state_changed()
    assert await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=0.5)

    from sase.ace.tui.widgets.decks.layout import toggle_nodes_collapsed

    app._deck_area_state = toggle_nodes_collapsed(app._deck_area_state)
    app._agents_deck_state_changed()
    release.set()
    while app._agents_deck_state_completed_generation < 2:
        await asyncio.sleep(0)

    assert len(saved) == 2
    assert saved[0].layout is DeckLayout.LEFT_RIGHT
    assert saved[0].nodes_collapsed is False
    assert saved[-1].layout is DeckLayout.LEFT_RIGHT
    assert saved[-1].nodes_collapsed is True


@pytest.mark.asyncio
async def test_flush_waits_for_latest_queued_generation() -> None:
    app = _Harness()
    app._agents_deck_state_merged = True
    app._agents_deck_state_last_snapshot = snapshot_from_area_state(
        app._deck_area_state
    )
    started = threading.Event()
    release = threading.Event()

    def _save(_snapshot: AgentsDeckStateSnapshot) -> None:
        started.set()
        release.wait(timeout=2)

    app._save_agents_deck_state_now = _save  # type: ignore[method-assign]
    app._deck_area_state = toggle_split(
        app._deck_area_state,
        DeckLayout.TOP_BOTTOM,
        DeckPanelState(DeckId.TOOLS),
    )
    app._agents_deck_state_changed()
    assert await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=0.5)

    flush = asyncio.create_task(app._flush_agents_deck_state())
    await asyncio.sleep(0)
    assert not flush.done()
    release.set()
    await asyncio.wait_for(flush, timeout=0.5)
    assert app._agents_deck_state_completed_generation == 1


def test_install_marks_deck_mode_only_sessions_merged() -> None:
    app = _Harness()
    app._decks_persistence_active = lambda: False  # type: ignore[method-assign]

    app._resolve_agents_deck_state_load(_split_snapshot())

    assert app._agents_deck_state_merged is True
    assert app.applied == []
    assert app._deck_area_state == DeckAreaState()
