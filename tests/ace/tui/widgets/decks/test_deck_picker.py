"""Pure coverage for the Agents deck picker model."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.layout import is_zoomed
from sase.ace.tui.widgets.decks.model import (
    DECK_CYCLE,
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)
from sase.ace.tui.widgets.decks.picker import (
    DeckPickerState,
    _deck_count_label,
    build_deck_picker_rows,
    deck_picker_heading,
    panel_position_label,
)
from sase.ace.tui.widgets.decks.titles import (
    DECK_BLURBS,
    DECK_COUNT_NOUNS,
    DECK_PICKER_KEYS,
    DECK_PICKER_RESERVED_KEYS,
)


def _availability() -> dict[DeckId, DeckAvailability]:
    return {
        DeckId.MAIN: DeckAvailability(True, 2),
        DeckId.FILES: DeckAvailability(True, 3),
        DeckId.TOOLS: DeckAvailability(False, 0),
    }


def _accents() -> dict[DeckId, str]:
    return {
        DeckId.MAIN: "#B48EAD",
        DeckId.FILES: "green",
        DeckId.TOOLS: "#87D7FF",
    }


def _state(
    current: DeckId = DeckId.MAIN,
    *,
    layout: DeckLayout = DeckLayout.SINGLE,
    focused: int = 0,
    other: tuple[DeckId, str] | None = None,
) -> DeckPickerState:
    return DeckPickerState(
        panel_index=focused,
        panel_label=(
            "deck" if layout is DeckLayout.SINGLE else ("bottom" if focused else "top")
        ),
        current=current,
        other=other,
        availability=_availability(),
        accents=_accents(),
    )


def test_picker_catalog_covers_every_deck() -> None:
    seen: set[str] = set()
    for deck in DECK_CYCLE:
        key = DECK_PICKER_KEYS[deck]
        assert len(key) == 1 and key.islower()
        assert key not in DECK_PICKER_RESERVED_KEYS
        assert key not in seen
        seen.add(key)
        assert DECK_BLURBS[deck]
        singular, plural = DECK_COUNT_NOUNS[deck]
        assert singular and plural and singular != plural
    assert set(DECK_PICKER_KEYS) == set(DECK_CYCLE)
    assert set(DECK_BLURBS) == set(DECK_CYCLE)
    assert set(DECK_COUNT_NOUNS) == set(DECK_CYCLE)


def test_deck_count_labels() -> None:
    assert _deck_count_label(DeckId.MAIN, DeckAvailability(True, 1)) == "1 card"
    assert _deck_count_label(DeckId.MAIN, DeckAvailability(True, 2)) == "2 cards"
    assert _deck_count_label(DeckId.FILES, DeckAvailability(True, 1)) == "1 file"
    assert _deck_count_label(DeckId.FILES, DeckAvailability(True, 5)) == "5 files"
    assert _deck_count_label(DeckId.TOOLS, DeckAvailability(True, 1)) == "1 call"
    assert _deck_count_label(DeckId.TOOLS, DeckAvailability(True, 4)) == "4 calls"
    assert _deck_count_label(DeckId.TOOLS, DeckAvailability(False, 0)) == "empty"
    assert _deck_count_label(DeckId.MAIN, DeckAvailability(None, None)) == ""
    assert _deck_count_label(DeckId.MAIN, None) == ""
    assert _deck_count_label(DeckId.MAIN, object()) == ""


def test_panel_position_labels() -> None:
    single = DeckAreaState()
    assert panel_position_label(single, 0) == "deck"

    top_bottom = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.TOP_BOTTOM,
    )
    assert panel_position_label(top_bottom, 0) == "top"
    assert panel_position_label(top_bottom, 1) == "bottom"

    left_right = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.LEFT_RIGHT,
    )
    assert panel_position_label(left_right, 0) == "left"
    assert panel_position_label(left_right, 1) == "right"

    zoomed = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.SINGLE,
        zoom_snapshot=DeckAreaState(
            panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
            focused=1,
            layout=DeckLayout.TOP_BOTTOM,
        ),
    )
    assert is_zoomed(zoomed)
    assert panel_position_label(zoomed, 1) == "zoomed"
    assert panel_position_label(zoomed, 0) == "zoomed"


def test_picker_rows_order_badges_and_other_panel() -> None:
    state = _state(
        DeckId.FILES,
        layout=DeckLayout.TOP_BOTTOM,
        focused=1,
        other=(DeckId.MAIN, "top"),
    )
    rows = build_deck_picker_rows(state)
    assert [row.deck for row in rows] == list(DECK_CYCLE)
    assert [row.key for row in rows] == ["m", "f", "t"]
    current = [row for row in rows if row.is_current]
    assert len(current) == 1 and current[0].deck is DeckId.FILES
    by_deck = {row.deck: row for row in rows}
    assert by_deck[DeckId.MAIN].other_panel_label == "top"
    assert by_deck[DeckId.FILES].other_panel_label is None
    assert by_deck[DeckId.TOOLS].other_panel_label is None
    assert by_deck[DeckId.MAIN].count_label == "2 cards"
    assert by_deck[DeckId.FILES].count_label == "3 files"
    assert by_deck[DeckId.TOOLS].count_label == "empty"
    assert by_deck[DeckId.TOOLS].has_content is False
    assert by_deck[DeckId.MAIN].blurb == "Context, prompt, and reply"


def test_picker_rows_omit_other_panel_when_single_or_zoomed() -> None:
    single_rows = build_deck_picker_rows(_state())
    assert all(row.other_panel_label is None for row in single_rows)

    zoomed = DeckPickerState(
        panel_index=1,
        panel_label="zoomed",
        current=DeckId.MAIN,
        other=None,
        availability=_availability(),
        accents=_accents(),
    )
    zoomed_rows = build_deck_picker_rows(zoomed)
    assert all(row.other_panel_label is None for row in zoomed_rows)


def test_picker_heading() -> None:
    assert deck_picker_heading(_state()) == "Choose what the deck panel shows"
    assert (
        deck_picker_heading(_state(layout=DeckLayout.TOP_BOTTOM, focused=1))
        == "Choose what the bottom panel shows"
    )
    zoomed = DeckPickerState(
        panel_index=0,
        panel_label="zoomed",
        current=DeckId.MAIN,
        other=None,
        availability=_availability(),
        accents=_accents(),
    )
    assert deck_picker_heading(zoomed) == "Choose what the zoomed panel shows"


def _hint_app(pick_deck: str) -> object:
    from sase.ace.tui.widgets.decks.panel_chrome import DeckPanelChromeMixin

    mixin = DeckPanelChromeMixin()
    mixin.app = SimpleNamespace(  # type: ignore[attr-defined]
        _keymap_registry=SimpleNamespace(
            app=SimpleNamespace(
                next_deck="ctrl+n", prev_deck="ctrl+p", pick_deck=pick_deck
            )
        )
    )
    return mixin


def test_deck_switch_hint_prefers_picker_chord() -> None:
    assert (
        _hint_app("p")._deck_switch_hint()  # type: ignore[attr-defined]
        == "p pick deck · Ctrl+N/Ctrl+P cycle decks"
    )


def test_deck_switch_hint_falls_back_without_picker_key() -> None:
    assert (
        _hint_app("unbound")._deck_switch_hint()  # type: ignore[attr-defined]
        == "Ctrl+N next deck · Ctrl+P previous deck"
    )
