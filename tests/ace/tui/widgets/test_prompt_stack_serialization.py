"""Tests for prompt stack parsing, construction, and serialization."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_stack import PromptStackState, split_prompt_text
from tests.ace.tui.widgets._prompt_stack_helpers import (
    snippet_target as _snippet_target,
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
