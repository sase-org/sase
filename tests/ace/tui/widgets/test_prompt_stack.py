"""Tests for the non-visual prompt stack state model.

Covers the Phase 1 deliverable of the multi-agent prompt stack: canonical
split/join, frontmatter handling, empty-segment dropping, and structural
operations (insert/remove/reorder/focus); relative focus and reorder cycle at
the stack edges, while absolute focus and removal clamp.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    SourceFingerprint,
    XPromptBinding,
    _SnippetPaneTarget,
    split_frontmatter,
    split_prompt_text,
)
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


def _snippet_target(
    trigger: str = "todo",
    *,
    loaded_body: str | None = None,
) -> _SnippetPaneTarget:
    return _SnippetPaneTarget(
        trigger=trigger,
        read_path="/tmp/sase.yml",
        write_path="/tmp/sase.yml",
        display_path="~/sase.yml",
        apply_target=None,
        via_chezmoi=False,
        exists=loaded_body is not None,
        loaded_body=loaded_body,
        loaded_fingerprint=None,
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


# --- from_panes: explicit verbatim seeding --------------------------------


def test_from_panes_one_pane_per_text() -> None:
    state = PromptStackState.from_panes(["first", "second", "third"])
    assert state.texts == ["first", "second", "third"]


def test_from_panes_does_not_split_embedded_separator() -> None:
    # A raw prompt that itself contains a real ``---`` separator must stay a
    # single pane so each killed agent maps to exactly one pane.
    state = PromptStackState.from_panes(["a\n---\nb", "c"])
    assert state.texts == ["a\n---\nb", "c"]
    assert len(state) == 2


def test_from_panes_keeps_frontmatter_inline() -> None:
    # Unlike ``from_text``, leading frontmatter is never lifted off the pane.
    state = PromptStackState.from_panes(["---\nname: foo\n---\nbody"])
    assert state.texts == ["---\nname: foo\n---\nbody"]
    assert state.frontmatter == ""


def test_from_panes_default_active_is_last() -> None:
    state = PromptStackState.from_panes(["a", "b", "c"])
    assert state.selected_index == 2


def test_from_panes_explicit_selected_index() -> None:
    state = PromptStackState.from_panes(["a", "b", "c"], selected_index=0)
    assert state.selected_index == 0


def test_from_panes_empty_yields_single_drafting_item() -> None:
    state = PromptStackState.from_panes([])
    assert state.texts == [""]
    assert len(state) == 1


def test_from_panes_item_ids_are_unique() -> None:
    state = PromptStackState.from_panes(["a", "b", "c"])
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


def test_snippet_body_does_not_make_stack_effectively_nonempty() -> None:
    state = PromptStackState.single("   ")
    state.append_snippet_pane("snippet body", _snippet_target())
    assert state.is_effectively_empty is True


# --- editor_markdown: spaced editor serialization -------------------------


def test_editor_markdown_pads_separators_with_blank_lines() -> None:
    state = PromptStackState.from_panes(["first prompt", "second prompt"])
    assert state.editor_markdown() == "first prompt\n\n---\n\nsecond prompt"


def test_editor_markdown_blank_line_before_first_body_with_frontmatter() -> None:
    state = PromptStackState.from_text("---\nmodel: opus\n---\nfirst\n---\nsecond")
    assert state.editor_markdown() == (
        "---\nmodel: opus\n---\n\nfirst\n\n---\n\nsecond"
    )


def test_editor_markdown_drops_empty_panes() -> None:
    state = PromptStackState.from_panes(["a", "   ", "b"])
    assert state.editor_markdown() == "a\n\n---\n\nb"


def test_editor_markdown_frontmatter_only_has_no_trailing_spacer() -> None:
    state = PromptStackState.from_text("---\nmodel: opus\n---\n")
    assert state.editor_markdown() == "---\nmodel: opus\n---"


def test_editor_markdown_round_trips_through_from_text() -> None:
    state = PromptStackState.from_text("---\nmodel: opus\n---\nfirst\n---\nsecond")
    reloaded = PromptStackState.from_text(state.editor_markdown())
    assert reloaded.texts == ["first", "second"]
    assert reloaded.frontmatter == "---\nmodel: opus\n---"


def test_snippet_body_is_excluded_from_launch_and_editor_payloads() -> None:
    state = PromptStackState.from_panes(["first", "second"])
    state.append_snippet_pane("snippet body", _snippet_target())

    assert len(state) == 3
    assert state.agent_texts == ["first", "second"]
    assert state.texts == ["first", "second"]
    assert state.join() == "first\n---\nsecond"
    assert state.editor_markdown() == "first\n\n---\n\nsecond"


# --- single() construction ------------------------------------------------


def test_single_keeps_separators_verbatim() -> None:
    """single() does not split; it stores text as one drafting item."""
    state = PromptStackState.single("a\n---\nb")
    assert state.texts == ["a\n---\nb"]
    assert state.selected_index == 0


def test_single_lifts_frontmatter_when_requested() -> None:
    state = PromptStackState.single(
        "---\ndescription: hi\n---\nbody", lift_frontmatter=True
    )
    assert state.texts == ["body"]
    assert state.frontmatter == "---\ndescription: hi\n---"
    assert state.join() == "---\ndescription: hi\n---\nbody"


def test_single_lift_frontmatter_preserves_plain_body_verbatim() -> None:
    text = "  \nbody with whitespace  \n"
    state = PromptStackState.single(text, lift_frontmatter=True)
    assert state.texts == [text]
    assert state.frontmatter == ""


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


# --- split_frontmatter: public lift of leading frontmatter -----------------


def test_split_frontmatter_lifts_leading_block() -> None:
    frontmatter = "---\ndescription: hi\n---"
    raw, body = split_frontmatter(f"{frontmatter}\nbody text")
    assert raw == frontmatter
    assert body == "body text"


def test_split_frontmatter_returns_empty_when_absent() -> None:
    raw, body = split_frontmatter("no frontmatter here")
    assert raw == ""
    assert body == "no frontmatter here"


# --- structured frontmatter model wiring ----------------------------------


def test_frontmatter_model_parses_raw_string() -> None:
    state = PromptStackState.from_text("---\nname: x\ndescription: hi\n---\nbody")
    model = state.frontmatter_model
    assert model.name == "x"
    assert model.description == "hi"


def test_frontmatter_model_empty_when_no_frontmatter() -> None:
    state = PromptStackState.from_text("a\n---\nb")
    assert state.frontmatter_model.is_empty


def test_set_frontmatter_model_writes_canonical_string() -> None:
    state = PromptStackState.from_text("seg1\n---\nseg2")
    model = PromptFrontmatter(name="x")
    model.set_input(InputArg(name="svc", type=InputType.WORD))
    state.set_frontmatter_model(model)
    assert state.frontmatter == "---\nname: x\ninput:\n  svc: word\n---"


def test_set_empty_frontmatter_model_clears_frontmatter() -> None:
    state = PromptStackState.from_text("---\nname: x\n---\nbody")
    state.set_frontmatter_model(PromptFrontmatter())
    assert state.frontmatter == ""
    # No stray delimiters leak into a whole-stack join.
    assert state.join() == "body"


def test_join_byte_stable_after_model_round_trip() -> None:
    """Reading then writing back the model leaves join() byte-identical."""
    text = "---\nname: x\ntags:\n- a\n- b\n---\nseg1\n---\nseg2"
    state = PromptStackState.from_text(text)
    before = state.join()
    state.set_frontmatter_model(state.frontmatter_model)
    assert state.join() == before


def test_attach_frontmatter_unchanged_after_model_edit() -> None:
    state = PromptStackState.from_text("---\nname: x\n---\nseg1\n---\nseg2")
    model = state.frontmatter_model
    model.description = "added"
    state.set_frontmatter_model(model)
    # attach_frontmatter still prepends the (now-updated) canonical block.
    assert state.attach_frontmatter("seg1") == (
        "---\nname: x\ndescription: added\n---\nseg1"
    )


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


def test_snippet_target_accessors_and_dirty_state() -> None:
    state = PromptStackState.single("agent")
    target = _snippet_target(loaded_body="original")
    snippet = state.append_snippet_pane("original", target)

    assert state.snippet_item is snippet
    assert state.snippet_index == 1
    assert state.has_snippet_pane is True
    assert state.agent_count == 1
    assert state.snippet_is_dirty is False

    snippet.text = "changed"
    assert state.snippet_is_dirty is True


def test_retarget_snippet_pane_keeps_body() -> None:
    state = PromptStackState.single("agent")
    state.append_snippet_pane("draft body", _snippet_target("old"))

    new_target = _snippet_target("new")
    state.retarget_snippet_pane(new_target)

    assert state.snippet_item is not None
    assert state.snippet_item.text == "draft body"
    assert state.snippet_item.snippet_target is new_target


def test_binding_dirty_and_external_change_detection(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    state = PromptStackState.from_text("body\n")
    state.bind(XPromptBinding.for_file(source))
    assert not state.is_dirty
    assert not state.source_changed()

    state.selected_item.text = "changed"
    assert state.is_dirty
    source.write_text("external\n", encoding="utf-8")
    assert state.source_changed()


def test_source_fingerprint_stat_signature_is_cheap_staleness_hint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    fingerprint = SourceFingerprint.from_path(source)

    assert SourceFingerprint.stat_signature(source) == (
        fingerprint.mtime_ns,
        fingerprint.size,
    )
    assert fingerprint.matches_stat(source)

    source.write_text("external\n", encoding="utf-8")
    assert not fingerprint.matches_stat(source)


def test_binding_uses_chezmoi_source_for_fingerprint_and_staleness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    source_root = home / ".local" / "share" / "chezmoi" / "home"
    read_path = home / "sase" / "xprompts" / "review.md"
    write_path = source_root / "sase" / "xprompts" / "review.md"
    read_path.parent.mkdir(parents=True)
    write_path.parent.mkdir(parents=True)
    read_path.write_text("applied\n", encoding="utf-8")
    write_path.write_text("body\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("sase.xprompt.write_targets.CHEZMOI_HOME", source_root)
    monkeypatch.setattr("sase.xprompt.write_targets.get_use_chezmoi", lambda: True)

    binding = XPromptBinding.for_file(read_path, reference="#review")
    state = PromptStackState.from_text("body\n")
    state.bind(binding)

    assert binding.path == str(read_path)
    assert binding.write_path == str(write_path)
    assert binding.apply_target == str(read_path)
    assert binding.via_chezmoi is True
    assert binding.reference == "#review"
    assert not state.source_changed()

    read_path.write_text("applied changed\n", encoding="utf-8")
    assert not state.source_changed()

    write_path.write_text("source changed\n", encoding="utf-8")
    assert state.source_changed()


def test_mark_written_refreshes_binding_and_clears_dirty(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("body\n", encoding="utf-8")
    state = PromptStackState.from_text("body")
    state.bind(XPromptBinding.for_file(source))
    state.selected_item.text = "changed"
    source.write_text("changed\n", encoding="utf-8")
    state.mark_written()
    assert not state.is_dirty
    assert not state.source_changed()


def test_bound_markdown_preserves_untouched_body_bytes(tmp_path: Path) -> None:
    source_text = "---\ndescription: old\n---\n\n  body with spaces  \n"
    source = tmp_path / "review.md"
    source.write_text(source_text, encoding="utf-8")
    state = PromptStackState.from_text(source_text)
    state.bind(XPromptBinding.for_file(source), source_markdown=source_text)

    frontmatter = state.frontmatter_model
    frontmatter.description = "new"
    rewritten = state.markdown_preserving_unchanged_body(frontmatter)

    assert rewritten == "---\ndescription: new\n---\n\n  body with spaces  \n"
