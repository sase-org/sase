"""Unified picker for stashed prompt drafts.

Lists stashed prompts newest-first with a relative age, an originating-project
chip, bundle marker, and a one-line preview. ``space`` marks a single-prompt
row to restore and keep, ``tab`` marks it to restore and pop, ``d`` marks any
row for deletion, and ``enter`` confirms. The modal is presentation-only: it
never touches the store. It dismisses with a :class:`StashRestoreResult`
describing which ids the app layer should pop, keep, or delete through
``prompt_stash_facade`` before loading the chosen drafts into the bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.prompt_stash_entries import entry_is_bundle, entry_prompt_segments
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.notifications.models import format_relative_time

from .base import OptionListNavigationMixin

# Sized so a full row (marker + age + project chip + bundle chip + preview) fits
# on one line inside the fixed 96-column modal — its option area is ~86 cols and
# the fixed columns ahead of the preview spend ~41.
_PREVIEW_WIDTH = 42
_PROJECT_WIDTH = 14
_AGE_WIDTH = 9
_BUNDLE_WIDTH = 10
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


def _bundle_chip(prompt_count: int) -> str:
    """Return a fixed-width bundle marker for a stash row."""
    label = f"{prompt_count} prompts" if prompt_count > 1 else ""
    if len(label) > _BUNDLE_WIDTH:
        label = f"{label[: _BUNDLE_WIDTH - 1]}…"
    return label.ljust(_BUNDLE_WIDTH)


def _stash_row_label(
    entry: PromptStashEntryWire,
    *,
    marked_for_pop: bool,
    marked_for_keep: bool,
    marked_for_delete: bool,
    age: str,
    prompt_count: int = 1,
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
    elif marked_for_pop:
        text.append("✓ ", style="bold #AF87FF")
    elif marked_for_keep:
        text.append("+ ", style="bold #5FD787")
    else:
        text.append("  ")

    row_style = "dim strike" if marked_for_delete else ""
    restoring = marked_for_pop or marked_for_keep
    text.append(
        age.rjust(_AGE_WIDTH), style="dim" if not marked_for_delete else row_style
    )
    text.append("  ")
    text.append(
        _project_chip(entry.project),
        style="cyan" if not marked_for_delete else row_style,
    )
    text.append("  ")
    text.append(
        _bundle_chip(prompt_count),
        style="magenta" if prompt_count > 1 and not marked_for_delete else row_style,
    )
    text.append("  ")
    preview = _first_line_preview(entry.text, preview_width)
    text.append(preview, style=row_style or ("bold" if restoring else ""))
    return text


@dataclass
class StashRestoreResult:
    """Outcome of the unified stash picker.

    ``pop_ids`` are loaded into the bar and removed from the stash; ``keep_ids``
    are loaded while staying stashed; ``delete_ids`` are removed without
    loading. Entries in none of these sets stay untouched. Order is irrelevant —
    the app re-sorts loaded entries by creation time before restoring them as
    panes.
    """

    pop_ids: list[str] = field(default_factory=list)
    keep_ids: list[str] = field(default_factory=list)
    delete_ids: list[str] = field(default_factory=list)


class StashedPromptsModal(
    OptionListNavigationMixin, ModalScreen["StashRestoreResult | None"]
):
    """Multi-select picker for restoring, keeping, and deleting stashed prompts."""

    _option_list_id = "stashed-prompts-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("tab", "toggle_pop", "Restore + pop", priority=True),
        ("space", "toggle_keep", "Restore + keep"),
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
        self._prompt_counts = {
            entry.id: len(entry_prompt_segments(entry)) for entry in self._entries
        }
        self._bundle_ids = {
            entry.id for entry in self._entries if entry_is_bundle(entry)
        }
        self._pop: set[str] = set()
        self._keep: set[str] = set()
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
        return f"Stashed prompts ({count})"

    def _hint_text(self) -> str:
        return (
            "j/k ↑/↓ navigate   space + restore+keep   tab ✓ restore+pop   "
            "d ✗ delete   a all   enter confirm   esc/q cancel"
        )

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for idx, entry in enumerate(self._entries):
            label = _stash_row_label(
                entry,
                marked_for_pop=entry.id in self._pop,
                marked_for_keep=entry.id in self._keep,
                marked_for_delete=entry.id in self._deleted,
                age=format_relative_time(entry.created_at),
                prompt_count=self._prompt_counts[entry.id],
            )
            options.append(Option(label, id=str(idx)))
        return options

    # -- selection state -----------------------------------------------------

    def _is_selectable(self, entry: PromptStashEntryWire) -> bool:
        return entry.id not in self._bundle_ids

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

    def action_toggle_pop(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if not self._is_selectable(entry):
            return
        if entry.id in self._pop:
            self._pop.discard(entry.id)
        else:
            self._pop.add(entry.id)
            self._keep.discard(entry.id)
            self._deleted.discard(entry.id)
        self._refresh_rows()

    def action_toggle_keep(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if not self._is_selectable(entry):
            return
        if entry.id in self._keep:
            self._keep.discard(entry.id)
        else:
            self._keep.add(entry.id)
            self._pop.discard(entry.id)
            self._deleted.discard(entry.id)
        self._refresh_rows()

    def action_toggle_all(self) -> None:
        selectable_ids = {
            entry.id for entry in self._entries if self._is_selectable(entry)
        }
        if not selectable_ids:
            return
        if selectable_ids <= self._pop:
            self._pop.difference_update(selectable_ids)
        else:
            self._pop.update(selectable_ids)
            self._keep.difference_update(selectable_ids)
            self._deleted.difference_update(selectable_ids)
        self._refresh_rows()

    def action_mark_delete(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._deleted:
            self._deleted.discard(entry.id)
        else:
            self._deleted.add(entry.id)
            self._pop.discard(entry.id)
            self._keep.discard(entry.id)
        self._refresh_rows()

    def action_confirm(self) -> None:
        pop_ids = [e.id for e in self._entries if e.id in self._pop]
        keep_ids = [e.id for e in self._entries if e.id in self._keep]
        delete_ids = [e.id for e in self._entries if e.id in self._deleted]
        if not pop_ids and not keep_ids and not delete_ids:
            highlighted = self._highlighted_entry()
            if highlighted is not None:
                pop_ids = [highlighted.id]
        if not pop_ids and not keep_ids and not delete_ids:
            self.dismiss(None)
            return
        self.dismiss(
            StashRestoreResult(
                pop_ids=pop_ids,
                keep_ids=keep_ids,
                delete_ids=delete_ids,
            )
        )

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        # ``enter`` (and click) confirms: restore the toggled set, or just the
        # highlighted row when nothing is toggled.
        self.action_confirm()


__all__ = [
    "StashRestoreResult",
    "StashedPromptsModal",
]
