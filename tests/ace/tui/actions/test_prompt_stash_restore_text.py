"""Tests for prompt-stash restore text combination helpers."""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
    PromptBarStashMixin,
)


def test_stash_entries_to_prompt_text_first_frontmatter_wins() -> None:
    from sase.core.prompt_stash_wire import PromptStashEntryWire

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
    from sase.core.prompt_stash_wire import PromptStashEntryWire

    entries = [
        PromptStashEntryWire(id="a", created_at="t1", text="solo"),
    ]
    assert PromptBarStashMixin._stash_entries_to_prompt_text(entries) == "solo"


def test_stash_entries_to_prompt_text_expands_bundle_rows() -> None:
    from sase.core.prompt_stash_wire import PromptStashEntryWire

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
