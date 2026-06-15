"""Tests for the non-visual prompt stack state model.

Covers the Phase 1 deliverable of the multi-agent prompt stack: canonical
split/join, frontmatter handling, empty-segment dropping, and structural
operations (insert/remove/reorder/focus) with selection clamping.
"""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    split_prompt_text,
)


# --- split_prompt_text: canonical parsing ---------------------------------


def test_split_plain_text_single_segment() -> None:
    assert split_prompt_text("Fix the bug") == ["Fix the bug"]


def test_split_two_segments() -> None:
    assert split_prompt_text("a\n---\nb") == ["a", "b"]


def test_split_drops_empty_segments() -> None:
    assert split_prompt_text("a\n---\n\n---\nb") == ["a", "b"]


def test_split_strips_segment_whitespace() -> None:
    assert split_prompt_text("  a  \n---\n  b  ") == ["a", "b"]


def test_split_protects_fenced_separator() -> None:
    text = "before\n```\ncode\n---\nstill code\n```\nafter"
    assert split_prompt_text(text) == [text]


# --- from_text: construction by splitting ---------------------------------


def test_from_text_single_item() -> None:
    state = PromptStackState.from_text("just one prompt")
    assert state.texts == ["just one prompt"]
    assert state.selected_index == 0


def test_from_text_multi_item() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    assert state.texts == ["a", "b", "c"]


def test_from_text_empty_yields_single_drafting_item() -> None:
    state = PromptStackState.from_text("")
    assert state.texts == [""]
    assert len(state) == 1


def test_from_text_all_empty_segments_yields_single_item() -> None:
    state = PromptStackState.from_text("   \n---\n   ")
    assert state.texts == [""]
    assert len(state) == 1


def test_bottom_item_is_default_active_after_split() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    assert state.selected_index == 2
    assert state.selected_item.text == "c"


def test_item_ids_are_unique() -> None:
    state = PromptStackState.from_text("a\n---\nb\n---\nc")
    ids = [item.item_id for item in state.items]
    assert len(set(ids)) == len(ids)


# --- frontmatter handling -------------------------------------------------


def test_frontmatter_not_treated_as_separator() -> None:
    text = "---\ntitle: x\n---\nseg1\n---\nseg2"
    state = PromptStackState.from_text(text)
    assert state.texts == ["seg1", "seg2"]


def test_frontmatter_preserved_on_state() -> None:
    text = "---\ntitle: x\n---\nbody"
    state = PromptStackState.from_text(text)
    assert state.texts == ["body"]
    assert state.frontmatter == "---\ntitle: x\n---"


def test_frontmatter_reattached_on_join() -> None:
    text = "---\ntitle: x\n---\nseg1\n---\nseg2"
    state = PromptStackState.from_text(text)
    assert state.join() == "---\ntitle: x\n---\nseg1\n---\nseg2"


def test_frontmatter_can_be_excluded_from_join() -> None:
    text = "---\ntitle: x\n---\nseg1\n---\nseg2"
    state = PromptStackState.from_text(text)
    assert state.join(include_frontmatter=False) == "seg1\n---\nseg2"


def test_no_frontmatter_means_empty_string() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    assert state.frontmatter == ""


def test_attach_frontmatter_prepends_to_single_pane_body() -> None:
    state = PromptStackState.from_text("---\ntitle: x\n---\nseg1\n---\nseg2")
    assert state.attach_frontmatter("seg1") == "---\ntitle: x\n---\nseg1"


def test_attach_frontmatter_is_noop_without_frontmatter() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    assert state.attach_frontmatter("a") == "a"


def test_attach_frontmatter_is_noop_for_empty_body() -> None:
    state = PromptStackState.from_text("---\ntitle: x\n---\nseg1\n---\nseg2")
    assert state.attach_frontmatter("") == ""


# --- split/join parity ----------------------------------------------------


def test_split_join_round_trip_multi() -> None:
    text = "a\n---\nb\n---\nc"
    assert PromptStackState.from_text(text).join() == text


def test_split_join_parity_with_fenced_separator() -> None:
    text = "before\n```\ncode\n---\nstill code\n```\nafter"
    state = PromptStackState.from_text(text)
    assert len(state) == 1
    assert state.join() == text


def test_join_drops_empty_items() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.append_bottom("   ")
    assert state.join() == "a\n---\nb"


def test_join_empty_stack_is_empty_string() -> None:
    assert PromptStackState.single("").join() == ""


def test_is_effectively_empty() -> None:
    assert PromptStackState.single("   ").is_effectively_empty is True
    assert PromptStackState.single("hi").is_effectively_empty is False


# --- single() construction ------------------------------------------------


def test_single_keeps_separators_verbatim() -> None:
    """single() does not split; it stores text as one drafting item."""
    state = PromptStackState.single("a\n---\nb")
    assert state.texts == ["a\n---\nb"]
    assert state.selected_index == 0


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
    # Already at the top: no change.
    assert state.move_focus(-1) is False
    assert state.selected_index == 0


def test_move_focus_clamps_at_bottom() -> None:
    state = PromptStackState.from_text("a\n---\nb")  # selected = 1 (bottom)
    assert state.move_focus(1) is False
    assert state.selected_index == 1


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


def test_move_selected_at_edge_is_noop() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    assert state.move_selected(-1) is False
    assert state.texts == ["a", "b"]
    assert state.selected_index == 0


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


# --- live split (typed `---`) ---------------------------------------------


def test_split_selected_live_two_segments() -> None:
    state = PromptStackState.single("alpha\n---\nbeta")
    assert state.split_selected_live() is True
    assert state.texts == ["alpha", "beta"]
    assert state.selected_index == 1


def test_split_selected_live_preserves_trailing_empty_pane() -> None:
    """A freshly typed trailing `---` yields a new empty bottom pane."""
    state = PromptStackState.single("foo\n---")
    assert state.split_selected_live() is True
    assert state.texts == ["foo", ""]
    assert state.selected_index == 1


def test_split_selected_live_preserves_trailing_empty_with_newline() -> None:
    state = PromptStackState.single("foo\n---\n")
    assert state.split_selected_live() is True
    assert state.texts == ["foo", ""]


def test_split_selected_live_noop_without_separator() -> None:
    state = PromptStackState.single("no separators here")
    assert state.split_selected_live() is False
    assert state.texts == ["no separators here"]


def test_split_selected_live_protects_fenced_separator() -> None:
    state = PromptStackState.single("```\n---\nstill code\n```")
    assert state.split_selected_live() is False
    assert state.texts == ["```\n---\nstill code\n```"]


def test_split_selected_live_protects_frontmatter_delimiters() -> None:
    """The `---` lines that bound YAML frontmatter never split the pane."""
    state = PromptStackState.single("---\nmodel: opus\n---\nbody")
    assert state.split_selected_live() is False
    assert state.texts == ["---\nmodel: opus\n---\nbody"]


def test_split_selected_live_lifts_frontmatter_and_splits_body() -> None:
    state = PromptStackState.single("---\nmodel: opus\n---\nalpha\n---\nbeta")
    assert state.split_selected_live() is True
    assert state.texts == ["alpha", "beta"]
    assert state.frontmatter == "---\nmodel: opus\n---"
    assert state.selected_index == 1


def test_split_selected_live_keeps_other_items() -> None:
    state = PromptStackState.from_text("first\n---\nsecond")
    state.focus(0)
    state.selected_item.text = "first\n---"
    assert state.split_selected_live() is True
    assert state.texts == ["first", "", "second"]
    assert state.selected_index == 1


# --- per-item editor state ------------------------------------------------


def test_item_defaults() -> None:
    item = PromptStackState.single("hi").selected_item
    assert item.mode == "insert"
    assert item.cursor == (0, 0)
    assert item.last_height is None


def test_reorder_preserves_item_editor_state() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    state.focus(0)
    state.selected_item.cursor = (3, 7)
    state.selected_item.mode = "normal"
    state.move_selected(1)
    moved = state.selected_item
    assert moved.text == "a"
    assert moved.cursor == (3, 7)
    assert moved.mode == "normal"


def test_prompt_stack_item_is_constructible() -> None:
    item = PromptStackItem(text="t", item_id="p0")
    assert item.text == "t"
    assert item.item_id == "p0"
