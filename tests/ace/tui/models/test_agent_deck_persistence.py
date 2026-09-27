"""Tests for the versioned Agents deck-layout persistence format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.models.agent_deck_persistence import (
    AgentsDeckStateSnapshot,
    _DeckPanelSnapshot,
    EMPTY_AGENTS_DECK_STATE,
    area_state_from_snapshot,
    load_agents_deck_state,
    save_agents_deck_state,
    snapshot_from_area_state,
    _serialize_agents_deck_state,
)
from sase.ace.tui.widgets.decks.layout import toggle_split, toggle_zoom
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
    DeckView,
    DeckViewPolicies,
    with_panel_view,
)


def _full_snapshot() -> AgentsDeckStateSnapshot:
    return AgentsDeckStateSnapshot(
        layout=DeckLayout.LEFT_RIGHT,
        ratio=30,
        focused=1,
        nodes_collapsed=True,
        panels=(
            _DeckPanelSnapshot(
                deck=DeckId.MAIN,
                preferred_cards={DeckId.MAIN: "reply"},
            ),
            _DeckPanelSnapshot(deck=DeckId.FILES),
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
    assert EMPTY_AGENTS_DECK_STATE.panels == (_DeckPanelSnapshot(deck=DeckId.MAIN),)


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
    assert loaded.panels == (_DeckPanelSnapshot(deck=DeckId.TOOLS),)


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
    assert loaded.panels[0] == _DeckPanelSnapshot(
        deck=DeckId.MAIN, preferred_cards={DeckId.MAIN: "reply"}
    )
    assert loaded.panels[1] == _DeckPanelSnapshot(deck=DeckId.MAIN)


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
    zoomed = toggle_zoom(split)
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
                    _DeckPanelSnapshot(
                        deck=DeckId.MAIN,
                        preferred_cards={DeckId.MAIN: f"card-{index}"},
                    )
                    for index in range(5000)
                ),
            )
        )


def test_views_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    snapshot = AgentsDeckStateSnapshot(
        layout=DeckLayout.LEFT_RIGHT,
        ratio=50,
        focused=0,
        nodes_collapsed=False,
        panels=(
            _DeckPanelSnapshot(
                deck=DeckId.MAIN,
                preferred_cards={DeckId.MAIN: "reply"},
                views=DeckViewPolicies(
                    main=DeckView.PAGE_BLOCKS, files=DeckView.SPREAD
                ),
            ),
            _DeckPanelSnapshot(deck=DeckId.FILES, views=DeckViewPolicies()),
        ),
    )
    save_agents_deck_state(snapshot, path)
    assert load_agents_deck_state(path) == snapshot
    serialized = path.read_text()
    assert '"views":{"files":"spread","main":"page_blocks"}' in serialized
    rebuilt = area_state_from_snapshot(
        snapshot_from_area_state(area_state_from_snapshot(snapshot))
    )
    assert rebuilt.panels[0].views.main is DeckView.PAGE_BLOCKS
    assert rebuilt.panels[0].views.files is DeckView.SPREAD


def test_legacy_file_without_views_decodes_to_auto(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [{"deck": "main", "preferred_card": "reply"}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].views == DeckViewPolicies()


def test_garbage_views_decode_to_auto(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "main",
                        "preferred_card": None,
                        "views": {
                            "main": "sideways",
                            "files": 42,
                            "unknown": "spread",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].views == DeckViewPolicies()
    # Non-object views also fail open to AUTO.
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "main",
                        "preferred_card": None,
                        "views": "spread",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_agents_deck_state(path).panels[0].views == DeckViewPolicies()


def test_files_page_blocks_decodes_to_auto(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "main",
                        "preferred_card": None,
                        "views": {
                            "main": "page_blocks",
                            "files": "page_blocks",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].views.main is DeckView.PAGE_BLOCKS
    assert loaded.panels[0].views.files is DeckView.AUTO


def test_zoom_unwrap_carries_views() -> None:
    split = toggle_split(
        DeckAreaState(), DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.FILES)
    )
    zoomed = toggle_zoom(split)
    edited = with_panel_view(zoomed, 0, DeckId.MAIN, DeckView.PAGE_CARDS)
    snapshot = snapshot_from_area_state(edited)
    assert snapshot.panels[0].views.main is DeckView.PAGE_CARDS
    rebuilt = area_state_from_snapshot(snapshot)
    assert rebuilt.panels[0].views.main is DeckView.PAGE_CARDS


def test_preferred_cards_round_trip_with_views(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    snapshot = AgentsDeckStateSnapshot(
        panels=(
            _DeckPanelSnapshot(
                deck=DeckId.MAIN,
                preferred_cards={DeckId.MAIN: "reply", DeckId.FILES: "notes"},
                views=DeckViewPolicies(main=DeckView.SPREAD),
            ),
        ),
    )
    save_agents_deck_state(snapshot, path)
    assert load_agents_deck_state(path) == snapshot
    serialized = path.read_text()
    assert '"preferred_card":"reply"' in serialized
    assert '"preferred_cards":{"files":"notes","main":"reply"}' in serialized
    rebuilt = area_state_from_snapshot(
        snapshot_from_area_state(area_state_from_snapshot(snapshot))
    )
    assert rebuilt.panels[0].preferred_card == "reply"
    assert rebuilt.panels[0].preferred_card_for(DeckId.FILES) == "notes"
    assert rebuilt.panels[0].views.main is DeckView.SPREAD


def test_legacy_file_without_map_decodes_legacy_as_main(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [{"deck": "main", "preferred_card": "reply"}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].preferred_cards == {DeckId.MAIN: "reply"}
    assert loaded.panels[0].preferred_card == "reply"


def test_map_wins_for_main_when_both_keys_present(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "main",
                        "preferred_card": "stale",
                        "preferred_cards": {"main": "reply", "files": "notes"},
                        "views": {"main": "spread", "files": "auto"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].preferred_cards == {
        DeckId.MAIN: "reply",
        DeckId.FILES: "notes",
    }
    assert loaded.panels[0].views.main is DeckView.SPREAD


def test_preferred_cards_skips_unknown_decks_and_bad_ids(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "main",
                        "preferred_card": None,
                        "preferred_cards": {
                            "main": "reply",
                            "telemetry": "x",
                            "files": "",
                            "tools": 42,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].preferred_cards == {DeckId.MAIN: "reply"}


def test_invalid_legacy_card_still_fails_panel_open(tmp_path: Path) -> None:
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [{"deck": "main", "preferred_card": 42}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels == (_DeckPanelSnapshot(deck=DeckId.MAIN),)


def test_final_panel_keeps_views(tmp_path: Path) -> None:
    """A FINAL panel round-trips as FINAL and keeps its Main/Files views."""
    path = tmp_path / "decks.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "layout": "single",
                "ratio": 50,
                "focused": 0,
                "nodes_collapsed": False,
                "panels": [
                    {
                        "deck": "final",
                        "preferred_cards": {"main": "reply"},
                        "views": {"main": "page_cards", "files": "spread"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_agents_deck_state(path)
    assert loaded.panels[0].deck is DeckId.FINAL
    assert loaded.panels[0].preferred_cards == {DeckId.MAIN: "reply"}
    assert loaded.panels[0].views == DeckViewPolicies(
        main=DeckView.PAGE_CARDS, files=DeckView.SPREAD
    )
