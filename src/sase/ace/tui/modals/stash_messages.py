"""Shared stash result, messages, and key bindings.

This module owns the public stash data types shared by both stash hosts (the
standalone picker and the tabbed overlay pane): the restore outcome, the
intent messages, and the shared key bindings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.binding import Binding
from textual.message import Message

from sase.core.prompt_stash_wire import PromptStashEntryWire

from .base import OptionListNavigationMixin
from .prompt_stash_row import INDEX_KEYS


def newest_first_stash_entries(
    entries: list[PromptStashEntryWire],
) -> list[PromptStashEntryWire]:
    """Return stash entries newest-first.

    Sorts by ``(created_at, pane_index)`` in reverse. ISO-8601 timestamps
    sort lexicographically; ties break by pane order so a "stash all" group
    keeps a stable display order.
    """
    return sorted(
        entries,
        key=lambda e: (e.created_at, e.pane_index),
        reverse=True,
    )


def single_restore_result(
    entry: PromptStashEntryWire,
    *,
    pinned: bool | None = None,
) -> StashRestoreResult:
    """Return the single-entry restore outcome for *entry*.

    Pinned entries restore with ``keep_ids`` (stay stashed); unpinned
    entries restore with ``pop_ids``. ``pinned`` defaults to
    ``entry.pinned``.
    """
    is_pinned = entry.pinned if pinned is None else pinned
    if is_pinned:
        return StashRestoreResult(keep_ids=[entry.id])
    return StashRestoreResult(pop_ids=[entry.id])


@dataclass
class StashRestoreResult:
    """Outcome of the unified stash picker.

    ``pop_ids`` are loaded into the bar and removed from the stash; ``keep_ids``
    are loaded while staying stashed; ``delete_ids`` are removed without
    loading; ``trash_ids`` move to Trash instead of permanent deletion (only
    the tabbed overlay produces these — the standalone picker keeps permanent
    ``delete_ids``). Entries in none of these sets stay untouched. Order is
    irrelevant — the app re-sorts loaded entries by creation time before
    restoring them as panes.
    """

    pop_ids: list[str] = field(default_factory=list)
    keep_ids: list[str] = field(default_factory=list)
    delete_ids: list[str] = field(default_factory=list)
    trash_ids: list[str] = field(default_factory=list)


class PinToggled(Message, namespace="stashed_prompts_modal"):
    """Posted when ``space`` toggles an entry's desired persisted pin state."""

    def __init__(self, entry: PromptStashEntryWire, pinned: bool) -> None:
        super().__init__()
        self.entry = entry
        self.pinned = pinned


class DeleteRequested(Message, namespace="stashed_prompts_modal"):
    """Posted when ``enter`` confirms a delete-only selection leaving rows.

    The app should delete these ids immediately while the panel stays open.
    """

    def __init__(self, entry_ids: list[str]) -> None:
        super().__init__()
        self.entry_ids = entry_ids


class TrashRequested(Message, namespace="stashed_prompts_modal"):
    """Posted when ``enter`` confirms a trash-only selection leaving rows.

    Only the tabbed overlay posts this (its delete marks mean Trash): the
    panel keeps its pending marks and the host confirms, moves the ids to
    Trash through Rust, then repaints authoritatively from the store outcome.
    """

    def __init__(self, entry_ids: list[str]) -> None:
        super().__init__()
        self.entry_ids = entry_ids


STASH_BINDINGS: list[Any] = [
    *OptionListNavigationMixin.NAVIGATION_BINDINGS,
    Binding("tab", "toggle_pop", "Restore", priority=True),
    ("space", "toggle_pin", "Pin"),
    ("a", "toggle_all", "All"),
    ("d", "mark_delete", "Delete"),
    ("D", "mark_delete_all", "Delete All"),
    Binding("ctrl+d", "scroll_preview_down", "Preview Down", priority=True),
    Binding("ctrl+u", "scroll_preview_up", "Preview Up", priority=True),
    *[
        Binding(key, f"restore_index({idx})", f"Restore #{idx + 1}", show=False)
        for idx, key in enumerate(INDEX_KEYS)
    ],
]


__all__ = [
    "DeleteRequested",
    "PinToggled",
    "STASH_BINDINGS",
    "StashRestoreResult",
    "TrashRequested",
    "newest_first_stash_entries",
    "single_restore_result",
]
