"""Restore picker for stashed prompt drafts (the ``,P`` modal).

Phase 3 of the prompt-stash feature.  Lists stashed prompts newest-first with a
relative age, an originating-project chip, and a one-line preview.  ``space``
toggles an entry for restore, ``a`` toggles all, ``d`` marks an entry for
deletion (discard without restoring), and ``enter`` confirms.  The modal is
presentation-only: it never touches the store.  It dismisses with a
:class:`StashRestoreResult` describing which entries to pop-and-load versus
pop-and-discard (boundary rule D6); the app layer performs the actual ``pop``
through ``prompt_stash_facade`` and loads the restored drafts into the bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.notifications.models import format_relative_time

from .base import OptionListNavigationMixin

_PREVIEW_WIDTH = 64
_PROJECT_WIDTH = 14
_AGE_WIDTH = 9
_PROJECT_PLACEHOLDER = "—"


def _first_line_preview(text: str, width: int) -> str:
    """Return the first non-blank line of *text*, truncated to *width*."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            preview = stripped
            break
    else:
        preview = text.strip()
    if len(preview) <= width:
        return preview
    if width <= 1:
        return preview[:width]
    return f"{preview[: width - 1]}…"


def _project_chip(project: str | None) -> str:
    """Return a fixed-width originating-project chip for a stash row."""
    label = project if project else _PROJECT_PLACEHOLDER
    if len(label) > _PROJECT_WIDTH:
        label = f"{label[: _PROJECT_WIDTH - 1]}…"
    return label.ljust(_PROJECT_WIDTH)


def _stash_row_label(
    entry: PromptStashEntryWire,
    *,
    selected: bool,
    marked_for_delete: bool,
    age: str,
    preview_width: int = _PREVIEW_WIDTH,
) -> Text:
    """Build the styled single-line label for one stash row.

    Kept as a pure helper (no widget access) so row rendering can be unit
    tested without a running app.  ``age`` is the already-formatted relative
    time so callers control the clock.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    if marked_for_delete:
        text.append("✗ ", style="bold red")
    elif selected:
        text.append("✓ ", style="bold #AF87FF")
    else:
        text.append("  ")

    row_style = "dim strike" if marked_for_delete else ""
    text.append(
        age.rjust(_AGE_WIDTH), style="dim" if not marked_for_delete else row_style
    )
    text.append("  ")
    text.append(
        _project_chip(entry.project),
        style="cyan" if not marked_for_delete else row_style,
    )
    text.append("  ")
    preview = _first_line_preview(entry.text, preview_width)
    text.append(preview, style=row_style or ("bold" if selected else ""))
    return text


@dataclass
class StashRestoreResult:
    """Outcome of the restore picker.

    ``restore_ids`` are popped from the store *and* loaded into the prompt bar;
    ``delete_ids`` are popped and discarded.  Entries in neither set stay in the
    store.  Order is irrelevant — the app re-sorts restored entries by creation
    time before loading them as panes.
    """

    restore_ids: list[str] = field(default_factory=list)
    delete_ids: list[str] = field(default_factory=list)


class StashedPromptsModal(
    OptionListNavigationMixin, ModalScreen["StashRestoreResult | None"]
):
    """Multi-select picker that pops stashed prompts back into the bar."""

    _option_list_id = "stashed-prompts-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("space", "toggle_row", "Toggle"),
        ("a", "toggle_all", "All"),
        ("d", "mark_delete", "Delete"),
    ]

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        # Newest first; ISO timestamps sort lexicographically, ties broken by
        # pane order so a "stash all" group keeps a stable display order.
        self._entries: list[PromptStashEntryWire] = sorted(
            entries,
            key=lambda e: (e.created_at, e.pane_index),
            reverse=True,
        )
        self._selected: set[str] = set()
        self._deleted: set[str] = set()

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="stashed-prompts-container"):
            yield Label(self._title_text(), id="stashed-prompts-title")
            yield OptionList(*self._build_options(), id="stashed-prompts-list")
            yield Static(self._hint_text(), id="stashed-prompts-hints")

    def on_mount(self) -> None:
        # Keep the list focused so j/k/space/a/d and enter all land on it.
        try:
            self.query_one("#stashed-prompts-list", OptionList).focus()
        except Exception:
            pass

    def _title_text(self) -> str:
        count = len(self._entries)
        noun = "prompt" if count == 1 else "prompts"
        return f"Restore stashed {noun} ({count})"

    @staticmethod
    def _hint_text() -> str:
        return (
            "j/k ↑/↓: navigate • space: select • a: all • "
            "d: delete • enter: restore • esc/q: cancel"
        )

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for idx, entry in enumerate(self._entries):
            label = _stash_row_label(
                entry,
                selected=entry.id in self._selected,
                marked_for_delete=entry.id in self._deleted,
                age=format_relative_time(entry.created_at),
            )
            options.append(Option(label, id=str(idx)))
        return options

    # -- selection state -----------------------------------------------------

    def _highlighted_entry(self) -> PromptStashEntryWire | None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._entries):
            return None
        return self._entries[highlighted]

    def _refresh_rows(self) -> None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)
        except Exception:
            return
        highlighted = option_list.highlighted
        option_list.clear_options()
        option_list.add_options(self._build_options())
        if self._entries and highlighted is not None:
            option_list.highlighted = min(highlighted, len(self._entries) - 1)

    def action_toggle_row(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._selected:
            self._selected.discard(entry.id)
        else:
            self._selected.add(entry.id)
            self._deleted.discard(entry.id)  # restore wins over delete
        self._refresh_rows()

    def action_toggle_all(self) -> None:
        all_ids = {entry.id for entry in self._entries}
        if all_ids <= self._selected:
            self._selected.clear()
        else:
            self._selected = all_ids
            self._deleted.clear()
        self._refresh_rows()

    def action_mark_delete(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._deleted:
            self._deleted.discard(entry.id)
        else:
            self._deleted.add(entry.id)
            self._selected.discard(entry.id)  # delete clears a pending restore
        self._refresh_rows()

    def action_confirm(self) -> None:
        restore_ids = [e.id for e in self._entries if e.id in self._selected]
        if not restore_ids:
            highlighted = self._highlighted_entry()
            if highlighted is not None and highlighted.id not in self._deleted:
                restore_ids = [highlighted.id]
        delete_ids = [e.id for e in self._entries if e.id in self._deleted]
        if not restore_ids and not delete_ids:
            self.dismiss(None)
            return
        self.dismiss(StashRestoreResult(restore_ids=restore_ids, delete_ids=delete_ids))

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        # ``enter`` (and click) confirms: restore the toggled set, or just the
        # highlighted row when nothing is toggled.
        self.action_confirm()


__all__ = [
    "StashRestoreResult",
    "StashedPromptsModal",
]
