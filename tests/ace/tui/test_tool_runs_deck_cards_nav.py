"""Default-card, tabs, switcher, and dispatch tests for the deck cards."""

from __future__ import annotations

from sase.ace.tui.tool_runs.deck import (
    TOOLS_LLM_CALLS_CARD_ID,
    TOOLS_RUNS_CARD_ID,
    _tools_switcher_text,
    tools_card_ids,
    tools_default_card,
    tools_picker_label,
    tools_switcher_segment,
    tools_tabs,
)
from sase.ace.tui.widgets.decks.card_documents import (
    CARD_DOCUMENT_DECKS,
    resolve_document_deck,
)
from sase.ace.tui.widgets.decks.model import (
    DeckId,
    DeckView,
    DeckViewPolicies,
    cycle_card_id,
)

__all__ = [
    "test_both_cards_tab_order_runs_first",
    "test_card_ids_runs_first",
    "test_ctrl_j_k_round_trip",
    "test_default_card_llm_calls_when_no_runs",
    "test_default_card_runs_first_without_preference",
    "test_default_card_sticky_wins",
    "test_every_deck_id_has_a_document_arm",
    "test_no_runs_node_keeps_single_llm_calls_tab",
    "test_picker_label_counts",
    "test_runs_only_node_shows_runs_only",
    "test_switcher_segment_never_contains_separator",
    "test_tools_has_no_view_policy",
    "test_tools_is_a_card_document_deck",
]


# Default-card rule: sticky wins, Runs when present, else LLM Calls.


def test_default_card_sticky_wins() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_default_card(ids, TOOLS_LLM_CALLS_CARD_ID) == TOOLS_LLM_CALLS_CARD_ID
    assert tools_default_card(ids, TOOLS_RUNS_CARD_ID) == TOOLS_RUNS_CARD_ID


def test_default_card_runs_first_without_preference() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_default_card(ids, None) == TOOLS_RUNS_CARD_ID
    assert tools_default_card(ids, "unknown-card") == TOOLS_RUNS_CARD_ID


def test_default_card_llm_calls_when_no_runs() -> None:
    assert tools_default_card((TOOLS_LLM_CALLS_CARD_ID,), None) == (
        TOOLS_LLM_CALLS_CARD_ID
    )
    assert tools_default_card((), None) is None


def test_card_ids_runs_first() -> None:
    assert tools_card_ids(True, True) == (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert tools_card_ids(False, True) == (TOOLS_LLM_CALLS_CARD_ID,)
    assert tools_card_ids(True, False) == (TOOLS_RUNS_CARD_ID,)


# Tabs: a no-runs node keeps a single LLM Calls tab; a monitor with
# runs and no calls shows Runs only.


def test_no_runs_node_keeps_single_llm_calls_tab() -> None:
    tabs = tools_tabs(False, True)
    assert [(tab.card_id, tab.title) for tab in tabs] == [
        (TOOLS_LLM_CALLS_CARD_ID, "LLM Calls")
    ]


def test_runs_only_node_shows_runs_only() -> None:
    tabs = tools_tabs(True, False)
    assert [(tab.card_id, tab.title) for tab in tabs] == [
        (TOOLS_RUNS_CARD_ID, "⚒ Runs")
    ]


def test_both_cards_tab_order_runs_first() -> None:
    tabs = tools_tabs(True, True)
    assert [tab.card_id for tab in tabs] == [
        TOOLS_RUNS_CARD_ID,
        TOOLS_LLM_CALLS_CARD_ID,
    ]


# Switcher segment never contains " · ".


def test_switcher_segment_never_contains_separator() -> None:
    cases = [
        _tools_switcher_text(0),
        _tools_switcher_text(1, 0),
        _tools_switcher_text(2, 57),
        _tools_switcher_text(1, 1),
        _tools_switcher_text(12, 300),
    ]
    assert _tools_switcher_text(2, 57) == "tools ⚒2 57"
    assert _tools_switcher_text(2) == "tools ⚒2"
    for text in cases:
        assert " · " not in text
    for live, silent in ((False, False), (True, False), (False, True)):
        segment = tools_switcher_segment(2, 57, live=live, silent=silent)
        assert " · " not in segment.plain


def test_picker_label_counts() -> None:
    assert tools_picker_label(2, 57) == "2 runs · 57 calls"
    assert tools_picker_label(1, 1) == "1 run · 1 call"
    assert tools_picker_label(2, None) == "2 runs"
    assert tools_picker_label(1, 0) == "1 run"
    assert tools_picker_label(0, 0) == "0 runs"
    assert tools_picker_label(None, 57) == "57 calls"
    assert tools_picker_label(None, None) == ""


# Ctrl+J/K round trip over the two Tools cards.


def test_ctrl_j_k_round_trip() -> None:
    ids = (TOOLS_RUNS_CARD_ID, TOOLS_LLM_CALLS_CARD_ID)
    assert cycle_card_id(ids, TOOLS_RUNS_CARD_ID, 1) == TOOLS_LLM_CALLS_CARD_ID
    assert cycle_card_id(ids, TOOLS_LLM_CALLS_CARD_ID, 1) == TOOLS_RUNS_CARD_ID
    assert cycle_card_id(ids, TOOLS_LLM_CALLS_CARD_ID, -1) == TOOLS_RUNS_CARD_ID


# Exhaustive per-deck dispatch: every DeckId has an arm.


def test_every_deck_id_has_a_document_arm() -> None:
    assert resolve_document_deck(DeckId.MAIN) is DeckId.MAIN
    assert resolve_document_deck(DeckId.FINAL) is DeckId.FINAL
    assert resolve_document_deck(DeckId.TOOLS) is DeckId.TOOLS
    assert resolve_document_deck(DeckId.FILES) is DeckId.MAIN


def test_tools_is_a_card_document_deck() -> None:
    assert DeckId.TOOLS in CARD_DOCUMENT_DECKS
    assert (DeckId.MAIN, DeckId.FINAL) == CARD_DOCUMENT_DECKS[:2]


# Tools stays paged-only: P is a no-op.


def test_tools_has_no_view_policy() -> None:
    policies = DeckViewPolicies()
    assert policies.for_deck(DeckId.TOOLS) is DeckView.AUTO
    try:
        policies.with_deck(DeckId.TOOLS, DeckView.SPREAD)
    except ValueError:
        pass
    else:
        raise AssertionError("Tools deck must reject a view policy")
