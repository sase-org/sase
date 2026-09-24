"""Tests for the versioned Agents deck-layout persistence format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models.agent_deck_persistence import (
    AgentsDeckStateSnapshot,
    DeckPanelSnapshot,
    EMPTY_AGENTS_DECK_STATE,
    area_state_from_snapshot,
    load_agents_deck_state,
    save_agents_deck_state,
    snapshot_from_area_state,
    _serialize_agents_deck_state,
)
from sase.ace.tui.widgets.decks.layout import enter_zoom, toggle_split
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)


def _full_snapshot() -> AgentsDeckStateSnapshot:
    return AgentsDeckStateSnapshot(
        layout=DeckLayout.LEFT_RIGHT,
        ratio=30,
        focused=1,
        nodes_collapsed=True,
        panels=(
            DeckPanelSnapshot(DeckId.MAIN, "reply"),
            DeckPanelSnapshot(DeckId.FILES, None),
        ),
    )


def test_deterministic_round_trip_covers_layout_and_panels(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    snapshot = _full_snapshot()

    save_agents_deck_state(snapshot, path)

    assert load_agents_deck_state(path) == snapshot
    first = path.read_text()
    save_agents_deck_state(snapshot, path)
    assert path.read_text() == first
    assert '"layout":"left-right"' in first
    assert '"nodes_collapsed":true' in first
    assert '"preferred_card":"reply"' in first


def test_empty_state_round_trips_to_single_main(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    save_agents_deck_state(EMPTY_AGENTS_DECK_STATE, path)
    assert load_agents_deck_state(path) == EMPTY_AGENTS_DECK_STATE
    assert EMPTY_AGENTS_DECK_STATE.layout is DeckLayout.SINGLE
    assert EMPTY_AGENTS_DECK_STATE.panels == (DeckPanelSnapshot(DeckId.MAIN, None),)


def test_missing_file_fails_open_to_empty(tmp_path: Path) -> None:
    assert load_agents_deck_state(tmp_path / "absent.json") == EMPTY_AGENTS_DECK_STATE


def test_corrupt_file_fails_open_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_agents_deck_state(path) == EMPTY_AGENTS_DECK_STATE


def test_wrong_shape_fails_open_to_empty(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text('["single"]', encoding="utf-8")
    assert load_agents_deck_state(path) == EMPTY_AGENTS_DECK_STATE


def test_unknown_layout_fails_open_while_panels_apply(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "diagonal",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [{"deck": "tools", "preferred_card": None}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.layout is DeckLayout.SINGLE
    assert loaded.panels == (DeckPanelSnapshot(DeckId.TOOLS, None),)


def test_unknown_deck_falls_back_to_main_panel(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "left-right",
                "ratio": 50,
                "focused": 1,
                "nodes_collapsed": False,
                "panels": [
                    {"deck": "main", "preferred_card": "reply"},
                    {"deck": "telemetry", "preferred_card": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.layout is DeckLayout.LEFT_RIGHT
    assert loaded.focused == 1
    assert loaded.panels[0] == DeckPanelSnapshot(DeckId.MAIN, "reply")
    assert loaded.panels[1] == DeckPanelSnapshot(DeckId.MAIN, None)


def test_unsupported_schema_version_fails_open(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps({"schema_version": 99, "panels": [{"deck": "main"}]}),
        encoding="utf-8",
    )
    assert load_agents_deck_state(path) == EMPTY_AGENTS_DECK_STATE


def test_oversized_file_fails_open(tmp_path: Path) -> None:
    from sase.ace.tui.models.agent_deck_persistence import MAX_FILE_BYTES

    path = tmp_path / "decks.json"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    assert load_agents_deck_state(path) == EMPTY_AGENTS_DECK_STATE


def test_snapshot_from_area_state_unwraps_zoom() -> None:
    split = toggle_split(
        DeckAreaState(), DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.FILES)
    )
    zoomed = enter_zoom(split)
    snapshot = snapshot_from_area_state(zoomed)
    assert snapshot.layout is DeckLayout.TOP_BOTTOM
    assert len(snapshot.panels) == 2
    assert snapshot.panels[1].deck is DeckId.FILES


def test_area_state_round_trip_through_snapshot() -> None:
    split = toggle_split(
        DeckAreaState(), DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS)
    )
    rebuilt = area_state_from_snapshot(snapshot_from_area_state(split))
    assert rebuilt.layout is split.layout
    assert rebuilt.focused == split.focused
    assert rebuilt.ratio == split.ratio
    assert rebuilt.nodes_collapsed == split.nodes_collapsed
    assert rebuilt.panels == split.panels
    assert rebuilt.zoom_snapshot is None


def test_serialize_rejects_oversize_payload() -> None:
    with pytest.raises(ValueError, match="exceeds maximum"):
        _serialize_agents_deck_state(
            AgentsDeckStateSnapshot(
                panels=tuple(
                    DeckPanelSnapshot(DeckId.MAIN, f"card-{index}")
                    for index in range(5000)
                ),
            )
        )
