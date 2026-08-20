"""Tests for prompt-stash restore text combination helpers."""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)
from sase.ace.tui.prompt_stash_entries import (
    RestoredStashPane,
    entries_to_restore_panes,
    restore_home_bar_focus,
)
from sase.core.prompt_stash_wire import PromptStashCursorWire, PromptStashEntryWire


def test_stash_entries_to_prompt_text_first_frontmatter_wins() -> None:
    entries = [
        PromptStashEntryWire(
            id="a", created_at="t1", text="one", frontmatter="model: c"
        ),
        PromptStashEntryWire(
            id="b", created_at="t2", text="two", frontmatter="model: d"
        ),
    ]
    assert (
        PromptBarStashMixin._stash_entries_to_prompt_text(entries)
        == "model: c\none\n---\ntwo"
    )


def test_stash_entries_to_prompt_text_no_frontmatter() -> None:
    entries = [
        PromptStashEntryWire(id="a", created_at="t1", text="solo"),
    ]
    assert PromptBarStashMixin._stash_entries_to_prompt_text(entries) == "solo"


def test_stash_entries_to_prompt_text_expands_bundle_rows() -> None:
    entries = [
        PromptStashEntryWire(
            id="a",
            created_at="t1",
            text="one\n---\ntwo",
            frontmatter="model: c",
        ),
        PromptStashEntryWire(id="b", created_at="t2", text="three"),
    ]
    assert (
        PromptBarStashMixin._stash_entries_to_prompt_text(entries)
        == "model: c\none\n---\ntwo\n---\nthree"
    )


def test_entries_to_restore_panes_marks_only_final_row_target() -> None:
    earlier = PromptStashEntryWire(
        id="a",
        created_at="t1",
        text="one",
        cursor=PromptStashCursorWire(pane_index=0, row=0, column=1),
    )
    bundle = PromptStashEntryWire(
        id="b",
        created_at="t2",
        text="alpha\n---\nbeta\n---\ngamma",
        frontmatter="model: c",
        cursor=PromptStashCursorWire(pane_index=1, row=2, column=3),
    )
    panes = entries_to_restore_panes([earlier, bundle])
    assert [pane.text for pane in panes] == ["one", "alpha", "beta", "gamma"]
    assert [pane.is_focus_target for pane in panes] == [False, False, True, False]
    assert panes[2].cursor == (2, 3)
    assert panes[0].cursor is None
    assert restore_home_bar_focus(panes) == (2, (2, 3))


def test_entries_to_restore_panes_ignores_invalid_index() -> None:
    entry = PromptStashEntryWire(
        id="a",
        created_at="t1",
        text="solo",
        cursor=PromptStashCursorWire(pane_index=4, row=0, column=0),
    )
    panes = entries_to_restore_panes([entry])
    assert panes == [RestoredStashPane(text="solo")]
    assert restore_home_bar_focus(panes) == (None, None)


def test_entries_to_restore_panes_legacy_row_is_cursorless() -> None:
    entry = PromptStashEntryWire(id="a", created_at="t1", text="alpha\n---\nbeta")
    panes = entries_to_restore_panes([entry])
    assert panes == [
        RestoredStashPane(text="alpha"),
        RestoredStashPane(text="beta"),
    ]
    assert restore_home_bar_focus(panes) == (None, None)
