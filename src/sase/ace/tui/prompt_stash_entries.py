"""Prompt-stash row helpers shared by the TUI restore boundary."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.core.prompt_stash_wire import PromptStashEntryWire


def entry_prompt_segments(entry: PromptStashEntryWire) -> list[str]:
    """Return the effective prompt bodies represented by one stash row."""
    return PromptStackState.from_text(entry.text).texts


def entries_to_restore_items(
    entries: list[PromptStashEntryWire],
) -> list[tuple[str, str]]:
    """Expand stash rows into ``(text, frontmatter)`` pane tuples."""
    items: list[tuple[str, str]] = []
    for entry in entries:
        for segment in entry_prompt_segments(entry):
            items.append((segment, entry.frontmatter))
    return items


__all__ = [
    "entries_to_restore_items",
    "entry_prompt_segments",
]
