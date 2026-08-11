"""Tests for prompt stack navigation and structural operations."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_stack import PromptStackState
from tests.ace.tui.widgets._prompt_stack_helpers import (
    snippet_target as _snippet_target,
)


# --- focus / navigation ---------------------------------------------------


def test_focus_clamps_out_of_range() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    assert state.focus(99) == 1
    assert state.focus(-5) == 0


def test_move_focus_up_and_down() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")  # selected = 2
    assert state.move_focus(-1) is True
    assert state.selected_index == 1
    assert state.move_focus(-1) is True
    assert state.selected_index == 0
    # From the top pane Ctrl+H wraps around to the bottom pane.
    assert state.move_focus(-1) is True
    assert state.selected_index == 2


def test_move_focus_cycles_from_bottom_to_top() -> None:
    state = PromptStackState.from_text("a\n---\nb")  # selected = 1 (bottom)
    # From the bottom pane Ctrl+L wraps around to the top pane.
    assert state.move_focus(1) is True
    assert state.selected_index == 0


def test_move_focus_single_pane_is_noop() -> None:
    state = PromptStackState.single("only")
    assert state.move_focus(1) is False
    assert state.move_focus(-1) is False
    assert state.selected_index == 0


# --- insert ---------------------------------------------------------------


def test_insert_below_selects_new_item() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    item = state.insert_below("new")
    assert state.texts == ["a", "new", "b"]
    assert state.selected_index == 1
    assert state.selected_item is item


def test_insert_below_without_select_keeps_selection() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    state.insert_below("new", select=False)
    assert state.texts == ["a", "new", "b"]
    assert state.selected_index == 0


def test_append_bottom_focuses_new_bottom() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    state.append_bottom("c")
    assert state.texts == ["a", "b", "c"]
    assert state.selected_index == 2


def test_append_bottom_inserts_above_snippet_pane() -> None:
    state = PromptStackState.single("agent")
    snippet = state.append_snippet_pane("snippet", _snippet_target())

    item = state.append_bottom("new agent")

    assert state.items == [state.agent_items[0], item, snippet]
    assert state.agent_texts == ["agent", "new agent"]
    assert state.snippet_index == 2
    assert state.selected_item is item


def test_insert_below_snippet_inserts_above_snippet_pane() -> None:
    state = PromptStackState.single("agent")
    snippet = state.append_snippet_pane("snippet", _snippet_target())

    item = state.insert_below("new agent")

    assert state.items == [state.agent_items[0], item, snippet]
    assert state.snippet_index == 2
    assert state.selected_item is item


def test_append_snippet_pane_allows_only_one_snippet() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("snippet", _snippet_target())

    with pytest.raises(ValueError):
        state.append_snippet_pane("second", _snippet_target("other"))


def test_inserted_items_get_unique_ids() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    existing = {item.item_id for item in state.items}
    new = state.append_bottom("c")
    assert new.item_id not in existing


# --- remove ---------------------------------------------------------------


def test_remove_selected_middle_clamps_to_next() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    state.focus(1)
    assert state.remove_selected() is True
    assert state.texts == ["a", "c"]
    # Selection stays at index 1, now pointing at "c".
    assert state.selected_index == 1
    assert state.selected_item.text == "c"


def test_remove_selected_bottom_clamps_into_range() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")  # selected = 2
    assert state.remove_selected() is True
    assert state.texts == ["a", "b"]
    assert state.selected_index == 1


def test_remove_selected_last_item_is_noop() -> None:
    state = PromptStackState.single("only")
    assert state.remove_selected() is False
    assert state.texts == ["only"]
    assert state.selected_index == 0


def test_remove_selected_refuses_to_remove_only_agent_with_snippet() -> None:
    state = PromptStackState.single("only agent")
    state.append_snippet_pane("snippet", _snippet_target())
    state.focus(0)

    assert state.remove_selected() is False
    assert state.agent_texts == ["only agent"]
    assert state.has_snippet_pane is True


def test_remove_snippet_pane_leaves_agent_items() -> None:
    state = PromptStackState.from_panes(["first", "second"])
    snippet = state.append_snippet_pane("snippet", _snippet_target())

    assert state.remove_snippet_pane() is snippet
    assert state.agent_texts == ["first", "second"]
    assert state.snippet_item is None


# --- reorder --------------------------------------------------------------


def test_move_selected_down_keeps_focus_on_item() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    state.focus(0)
    assert state.move_selected(1) is True
    assert state.texts == ["b", "a", "c"]
    assert state.selected_index == 1
    assert state.selected_item.text == "a"


def test_move_selected_up_keeps_focus_on_item() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")  # selected = 2
    assert state.move_selected(-1) is True
    assert state.texts == ["a", "c", "b"]
    assert state.selected_index == 1
    assert state.selected_item.text == "c"


def test_move_selected_top_wraps_to_bottom() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    state.focus(0)
    moved_id = state.selected_item.item_id
    # Ctrl+Shift+H from the top pane wraps it to the bottom of the stack.
    assert state.move_selected(-1) is True
    assert state.texts == ["b", "c", "a"]
    assert state.selected_index == 2
    assert state.selected_item.item_id == moved_id


def test_move_selected_bottom_wraps_to_top() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")  # selected = 2
    moved_id = state.selected_item.item_id
    # Ctrl+Shift+L from the bottom pane wraps it to the top of the stack.
    assert state.move_selected(1) is True
    assert state.texts == ["c", "a", "b"]
    assert state.selected_index == 0
    assert state.selected_item.item_id == moved_id


def test_move_selected_single_pane_is_noop() -> None:
    state = PromptStackState.single("only")
    assert state.move_selected(1) is False
    assert state.move_selected(-1) is False
    assert state.texts == ["only"]
    assert state.selected_index == 0


def test_move_selected_refuses_snippet_item() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("snippet", _snippet_target())

    assert state.selected_item.is_snippet_pane
    assert state.move_selected(-1) is False
    assert state.agent_texts == ["agent"]
    assert state.snippet_index == 1


def test_move_selected_refuses_to_move_agent_past_snippet() -> None:
    state = PromptStackState.from_panes(["first", "second"])
    state.append_snippet_pane("snippet", _snippet_target())
    state.focus(1)

    assert state.move_selected(1) is False
    assert state.agent_texts == ["first", "second"]
    assert state.snippet_index == 2


def test_move_selected_preserves_item_identity() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    state.focus(0)
    moved_id = state.selected_item.item_id
    state.move_selected(2)
    assert state.selected_index == 2
    assert state.selected_item.item_id == moved_id


# --- split in place -------------------------------------------------------


def test_split_selected_expands_item() -> None:
    state = PromptStackState.single("a\n---\nb\n---\nc")
    assert state.split_selected() is True
    assert state.texts == ["a", "b", "c"]
    # Bottom new pane becomes active.
    assert state.selected_index == 2


def test_split_selected_noop_for_single_segment() -> None:
    state = PromptStackState.single("no separators here")
    assert state.split_selected() is False
    assert state.texts == ["no separators here"]


def test_split_selected_keeps_other_items() -> None:
    state = PromptStackState.from_text("first\n---\nsecond")
    state.focus(0)
    state.selected_item.text = "x\n---\ny"
    assert state.split_selected() is True
    assert state.texts == ["x", "y", "second"]
    assert state.selected_index == 1


def test_split_selected_is_noop_on_snippet_pane() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("x\n---\ny", _snippet_target())

    assert state.split_selected() is False
    assert state.agent_texts == ["agent"]
    assert state.snippet_item is not None
    assert state.snippet_item.text == "x\n---\ny"


# --- load_segments_at: in-place load preserving neighbors -----------------


def test_load_segments_at_single_replaces_in_place() -> None:
    state = PromptStackState.from_panes(["a", "b", "c"])
    state.load_segments_at(1, ["REPLACED"])
    assert state.texts == ["a", "REPLACED", "c"]
    assert state.selected_index == 1


def test_load_segments_at_multi_inserts_below_preserving_neighbors() -> None:
    # [A, B*, C] + entry x---y---z -> [A, x*, y, z, C] (spec example).
    state = PromptStackState.from_panes(["a", "b", "c"], selected_index=1)
    state.load_segments_at(1, ["x", "y", "z"])
    assert state.texts == ["a", "x", "y", "z", "c"]
    assert state.selected_index == 1


def test_load_segments_at_selection_stays_on_index() -> None:
    state = PromptStackState.from_panes(["a", "b", "c"])
    state.load_segments_at(2, ["p", "q"])
    assert state.texts == ["a", "b", "p", "q"]
    assert state.selected_index == 2


def test_load_segments_at_inserted_items_have_unique_ids() -> None:
    state = PromptStackState.from_panes(["a", "b"])
    state.load_segments_at(0, ["x", "y", "z"])
    ids = [item.item_id for item in state.items]
    assert len(ids) == len(set(ids))


def test_load_segments_at_empty_list_clears_pane_text() -> None:
    state = PromptStackState.from_panes(["a", "b"])
    state.load_segments_at(0, [])
    assert state.texts == ["", "b"]
    assert state.selected_index == 0


def test_load_segments_at_clamps_out_of_range_index() -> None:
    state = PromptStackState.from_panes(["a", "b"])
    state.load_segments_at(9, ["z"])
    assert state.texts == ["a", "z"]
    assert state.selected_index == 1


def test_load_segments_at_is_noop_on_snippet_pane() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("snippet", _snippet_target())

    state.load_segments_at(1, ["x", "y"])

    assert state.agent_texts == ["agent"]
    assert state.snippet_item is not None
    assert state.snippet_item.text == "snippet"
    assert state.selected_item.is_snippet_pane
