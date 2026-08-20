"""Prompt-stash row helpers shared by the TUI restore boundary."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.core.prompt_stash_wire import PromptStashEntryWire


@dataclass(frozen=True)
class RestoredStashPane:
    """One expanded stash pane ready to load into the prompt bar."""

    text: str
    frontmatter: str = ""
    cursor: tuple[int, int] | None = None
    is_focus_target: bool = False


def entry_prompt_segments(entry: PromptStashEntryWire) -> list[str]:
    """Return the effective prompt bodies represented by one stash row."""
    return PromptStackState.from_text(entry.text).texts


def _cursor_target_for_entry(
    entry: PromptStashEntryWire, segments: list[str]
) -> tuple[int, tuple[int, int]] | None:
    """Return ``(segment_index, cursor)`` when *entry* has a usable cursor."""
    cursor = entry.cursor
    if cursor is None:
        return None
    pane_index = cursor.pane_index
    if pane_index < 0 or pane_index >= len(segments):
        return None
    return pane_index, (cursor.row, cursor.column)


def entries_to_restore_panes(
    entries: list[PromptStashEntryWire],
) -> list[RestoredStashPane]:
    """Expand stash rows into panes, marking at most the final row's target.

    Oldest-first restore order is the caller's responsibility. Only the last
    row's saved cursor can become a focus target; an invalid bundle-local
    index is ignored so restore falls back to the last pane at end of text.
    """
    panes: list[RestoredStashPane] = []
    last_index = len(entries) - 1
    for entry_index, entry in enumerate(entries):
        segments = entry_prompt_segments(entry)
        target = (
            _cursor_target_for_entry(entry, segments)
            if entry_index == last_index
            else None
        )
        target_index, target_cursor = target if target is not None else (None, None)
        for segment_index, segment in enumerate(segments):
            is_target = target_index is not None and segment_index == target_index
            panes.append(
                RestoredStashPane(
                    text=segment,
                    frontmatter=entry.frontmatter,
                    cursor=target_cursor if is_target else None,
                    is_focus_target=is_target,
                )
            )
    return panes


def restore_home_bar_focus(
    panes: list[RestoredStashPane],
) -> tuple[int | None, tuple[int, int] | None]:
    """Return the parsed-stack pane index and cursor for a fresh home bar.

    Empty segments are dropped from the joined home-bar text, so a focus
    target that would not appear in the parsed stack is ignored.
    """
    visible = [pane for pane in panes if pane.text.strip()]
    if not visible:
        target = next((pane for pane in panes if pane.is_focus_target), None)
        if target is None:
            return None, None
        return 0, target.cursor
    target_index = next(
        (index for index, pane in enumerate(visible) if pane.is_focus_target),
        None,
    )
    if target_index is None:
        return None, None
    return target_index, visible[target_index].cursor


__all__ = [
    "RestoredStashPane",
    "entries_to_restore_panes",
    "entry_prompt_segments",
    "restore_home_bar_focus",
]
