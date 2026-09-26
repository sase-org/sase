"""Reusable Stash pane and its shared controller logic.

This module owns the stash list/preview UI and interaction logic shared by
the standalone :class:`StashedPromptsModal` and the tabbed
:class:`PromptsModal` overlay. The logic lives in
:class:`StashControllerMixin` so both hosts keep identical behavior; the
modal keeps its exact DOM while :class:`StashPane` renders only the
list/preview panels (the overlay shell owns the heading and footer).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.xprompt_syntax import highlight_prompt_text
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.project_display_names import ProjectDisplaySnapshot

from .base import OptionListNavigationMixin
from ._prompt_stash_preview import PromptStashPreviewPane, tagified_stash_text
from .prompt_stash_row import (
    DEFAULT_STASH_PREVIEW_WIDTH,
    INDEX_KEYS,
    PIN_GLYPH,
    append_shortcut,
    prompt_stash_preview_width_for_list_content,
    stash_row_age,
    stash_row_label,
)

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


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


class StashControllerMixin:
    """Shared stash list/preview state and interactions.

    Hosts (the standalone modal and the overlay pane) provide ``_emit_result``
    and compose the shared pieces. ``_option_list_id`` must name the stash
    ``OptionList`` DOM id on the host.
    """

    if TYPE_CHECKING:
        _entries: list[PromptStashEntryWire]

        def _emit_result(self, result: StashRestoreResult | None = None) -> None: ...

    _option_list_id = "stashed-prompts-list"

    def _init_stash_controller(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
    ) -> None:
        # Newest first; ISO timestamps sort lexicographically, ties broken by
        # pane order so a "stash all" group keeps a stable display order.
        self._entries: list[PromptStashEntryWire] = sorted(
            entries,
            key=lambda e: (e.created_at, e.pane_index),
            reverse=True,
        )
        self._project_display_snapshot = (
            project_display_snapshot or ProjectDisplaySnapshot()
        )
        self._prompt_counts = {
            entry.id: len(entry_prompt_segments(entry)) for entry in self._entries
        }
        self._pop: set[str] = set()
        self._pinned: set[str] = {entry.id for entry in self._entries if entry.pinned}
        self._deleted: set[str] = set()
        self._highlight_cache: dict[str, Text] = {}
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._refreshing_options = False
        self._narrow = True
        self._last_preview_width_budget = DEFAULT_STASH_PREVIEW_WIDTH

    # -- layout --------------------------------------------------------------

    def _compose_stash_list_panel(self, *, with_chrome: bool) -> ComposeResult:
        """Yield the list column, with title/hints only for standalone use."""
        with Vertical(id="stashed-prompts-list-panel"):
            if with_chrome:
                yield Label(self._title_text(), id="stashed-prompts-title")
            yield OptionList(*self._build_options(), id="stashed-prompts-list")
            if with_chrome:
                yield Static(self._hint_text(), id="stashed-prompts-hints")

    def _compose_stash_panels(self, *, with_chrome: bool) -> ComposeResult:
        with Horizontal(id="stashed-prompts-panels"):
            yield from self._compose_stash_list_panel(with_chrome=with_chrome)
            yield PromptStashPreviewPane(id="stashed-prompts-preview-pane")

    def _compose_stash_modal_body(self) -> ComposeResult:
        """Full standalone-modal body: title, panels, and footer."""
        with Container(id="stashed-prompts-container"):
            yield from self._compose_stash_panels(with_chrome=True)

    def _on_stash_mount(self) -> None:
        # Keep the list focused so j/k/space/tab/a/d and enter all land on it.
        self._preview_debouncer = DetailPanelDebouncer(self.app)  # type: ignore[attr-defined]
        self._set_narrow_mode(self.app.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)  # type: ignore[attr-defined]
        try:
            self.query_one("#stashed-prompts-list", OptionList).focus()  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._entries:
            self._paint_preview(self._entries[0].id)
        else:
            self.query_one(PromptStashPreviewPane).show_placeholder()  # type: ignore[attr-defined]
        self.call_after_refresh(self._refresh_rows_for_current_width)  # type: ignore[attr-defined]

    def _on_stash_unmount(self) -> None:
        if self._preview_debouncer is not None:
            self._preview_debouncer.cancel()

    def _on_stash_resize(self, event: events.Resize) -> None:
        """Collapse the preview on narrow terminals and resize row snippets."""
        self._set_narrow_mode(event.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        self.call_after_refresh(self._refresh_rows_for_current_width)  # type: ignore[attr-defined]

    def focus_stash_list(self) -> None:
        """Focus the stash list, falling back silently when it is not mounted."""
        try:
            self.query_one("#stashed-prompts-list", OptionList).focus()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _title_text(self) -> str:
        count = len(self._entries)
        return f"Stashed prompts ({count})"

    def _hint_text(self) -> str:
        return (
            "1-9/0 restore · a all · j/k move · enter · esc/q · ^d/u\n"
            f"space {PIN_GLYPH} pin · tab ✓ · d delete row · D delete all"
        )

    def _build_options(self, *, preview_width: int | None = None) -> list[Option]:
        if preview_width is None:
            preview_width = self._last_preview_width_budget
        self._last_preview_width_budget = preview_width
        options: list[Option] = []
        for idx, entry in enumerate(self._entries):
            label = Text(no_wrap=True, overflow="ellipsis")
            shortcut = INDEX_KEYS[idx] if idx < len(INDEX_KEYS) else None
            append_shortcut(label, shortcut)
            label.append_text(
                stash_row_label(
                    entry,
                    marked_for_pop=entry.id in self._pop,
                    marked_for_delete=entry.id in self._deleted,
                    pinned=entry.id in self._pinned,
                    age=stash_row_age(entry),
                    prompt_count=self._prompt_counts[entry.id],
                    preview_width=preview_width,
                    project_display_snapshot=self._project_display_snapshot,
                )
            )
            options.append(Option(label, id=str(idx)))
        return options

    # -- selection state -----------------------------------------------------

    def _highlighted_index_and_entry(
        self,
    ) -> tuple[int, PromptStashEntryWire] | None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._entries):
            return None
        return highlighted, self._entries[highlighted]

    def _highlighted_entry(self) -> PromptStashEntryWire | None:
        highlighted = self._highlighted_index_and_entry()
        if highlighted is None:
            return None
        return highlighted[1]

    def _refresh_rows(self) -> None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        highlighted = option_list.highlighted
        self._refreshing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(self._build_options())
            if self._entries and highlighted is not None:
                option_list.highlighted = min(highlighted, len(self._entries) - 1)
        finally:
            self._refreshing_options = False

    def _resolve_preview_width_budget(self) -> int:
        if self._narrow:
            return DEFAULT_STASH_PREVIEW_WIDTH
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return DEFAULT_STASH_PREVIEW_WIDTH
        width = option_list.scrollable_content_region.width
        if width <= 0:
            width = option_list.content_size.width
        if width <= 0:
            width = option_list.size.width
        return prompt_stash_preview_width_for_list_content(width)

    def _refresh_rows_for_current_width(self) -> None:
        preview_width = self._resolve_preview_width_budget()
        if preview_width == self._last_preview_width_budget:
            return
        self._last_preview_width_budget = preview_width
        self._refresh_rows()

    def _set_narrow_mode(self, narrow: bool) -> None:
        self._narrow = narrow
        try:
            container = self.query_one("#stashed-prompts-container", Container)  # type: ignore[attr-defined]
        except Exception:
            return
        container.set_class(narrow, "-narrow")

    def _schedule_preview(self, entry_id: str) -> None:
        if self._preview_debouncer is None:
            self._paint_preview(entry_id)
            return
        self._preview_debouncer.schedule(
            lambda: self._paint_preview_if_current(entry_id)
        )

    def _paint_preview_if_current(self, entry_id: str) -> None:
        entry = self._highlighted_entry()
        if entry is not None and entry.id == entry_id:
            self._paint_preview(entry_id)

    def _paint_preview(self, entry_id: str) -> None:
        entry = next((item for item in self._entries if item.id == entry_id), None)
        if entry is None:
            self.query_one(PromptStashPreviewPane).show_placeholder()  # type: ignore[attr-defined]
            return
        highlighted = self._highlight_cache.get(entry.id)
        if highlighted is None:
            highlighted = highlight_prompt_text(tagified_stash_text(entry.text))
            self._highlight_cache[entry.id] = highlighted
        self.query_one(PromptStashPreviewPane).show_entry(  # type: ignore[attr-defined]
            entry,
            prompt_count=self._prompt_counts[entry.id],
            highlighted_body=highlighted,
            project_display_snapshot=self._project_display_snapshot,
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Debounce the expensive preview paint while navigation stays instant."""
        if self._refreshing_options or event.option is None or event.option.id is None:
            return
        try:
            index = int(event.option.id)
        except ValueError:
            return
        if 0 <= index < len(self._entries):
            self._schedule_preview(self._entries[index].id)

    def action_scroll_preview_down(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(1)  # type: ignore[attr-defined]

    def action_scroll_preview_up(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(-1)  # type: ignore[attr-defined]

    def action_toggle_pop(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._pop:
            self._pop.discard(entry.id)
        else:
            self._pop.add(entry.id)
            self._deleted.discard(entry.id)
        self._refresh_rows()

    def action_toggle_pin(self) -> None:
        highlighted = self._highlighted_index_and_entry()
        if highlighted is None:
            return
        index, entry = highlighted
        pinned = entry.id not in self._pinned
        if pinned:
            self._pinned.add(entry.id)
        else:
            self._pinned.discard(entry.id)
        updated = replace(entry, pinned=pinned)
        self._entries[index] = updated
        self._refresh_rows()
        self._schedule_preview(updated.id)
        self.post_message(PinToggled(updated, pinned))  # type: ignore[attr-defined]

    def action_toggle_all(self) -> None:
        entry_ids = {entry.id for entry in self._entries}
        if not entry_ids:
            return
        if entry_ids <= self._pop:
            self._pop.difference_update(entry_ids)
        else:
            self._pop.update(entry_ids)
            self._deleted.difference_update(entry_ids)
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
        self._refresh_rows()

    def action_mark_delete_all(self) -> None:
        entry_ids = {entry.id for entry in self._entries}
        if not entry_ids:
            return
        self._deleted.update(entry_ids)
        self._pop.difference_update(entry_ids)
        self._refresh_rows()

    def _single_restore_result(self, entry: PromptStashEntryWire) -> StashRestoreResult:
        if entry.id in self._pinned:
            return StashRestoreResult(keep_ids=[entry.id])
        return StashRestoreResult(pop_ids=[entry.id])

    def action_restore_index(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            return
        self._emit_result(self._single_restore_result(self._entries[index]))

    def _apply_deletions_in_place(self, delete_ids: list[str]) -> None:
        highlighted = self._highlighted_index_and_entry()
        old_index: int | None = highlighted[0] if highlighted is not None else None
        old_id: str | None = highlighted[1].id if highlighted is not None else None
        self.post_message(DeleteRequested(list(delete_ids)))  # type: ignore[attr-defined]
        deleted = set(delete_ids)
        self._entries = [e for e in self._entries if e.id not in deleted]
        for entry_id in deleted:
            self._prompt_counts.pop(entry_id, None)
            self._highlight_cache.pop(entry_id, None)
            self._pinned.discard(entry_id)
            self._pop.discard(entry_id)
        self._deleted.clear()
        try:
            self.query_one("#stashed-prompts-title", Label).update(self._title_text())  # type: ignore[attr-defined]
        except Exception:
            pass
        self._refresh_rows()
        if not self._entries:
            return
        new_index: int | None = None
        if old_id is not None:
            for idx, entry in enumerate(self._entries):
                if entry.id == old_id:
                    new_index = idx
                    break
        if new_index is None and old_index is not None:
            new_index = min(old_index, len(self._entries) - 1)
        if new_index is None:
            new_index = 0
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        option_list.highlighted = new_index
        self._paint_preview(self._entries[new_index].id)

    def action_confirm(self) -> None:
        marked = [e.id for e in self._entries if e.id in self._pop]
        pop_ids = [entry_id for entry_id in marked if entry_id not in self._pinned]
        keep_ids = [entry_id for entry_id in marked if entry_id in self._pinned]
        delete_ids = [e.id for e in self._entries if e.id in self._deleted]
        if not marked and delete_ids and len(delete_ids) < len(self._entries):
            self._apply_deletions_in_place(delete_ids)
            return
        if not marked and not delete_ids:
            highlighted = self._highlighted_entry()
            if highlighted is not None:
                self._emit_result(self._single_restore_result(highlighted))
                return
            self._emit_result(None)
            return
        self._emit_result(
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


class StashPane(StashControllerMixin, OptionListNavigationMixin, Widget):
    """Reusable stash list/preview pane for the tabbed Prompts overlay.

    The overlay shell owns the heading and footer; this pane renders only the
    list/preview panels and reports outcomes as :class:`StashPane.Selected`
    instead of dismissing a screen.
    """

    class Selected(Message):
        """Posted when the stash pane resolves to a restore outcome or cancel."""

        def __init__(self, result: StashRestoreResult | None) -> None:
            super().__init__()
            self.result = result

    # Re-export the shared stash messages so hosts can reference one home.
    PinToggled = PinToggled
    DeleteRequested = DeleteRequested

    BINDINGS = STASH_BINDINGS

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
    ) -> None:
        super().__init__()
        self._init_stash_controller(
            entries, project_display_snapshot=project_display_snapshot
        )

    def dismiss(self, result: StashRestoreResult | None = None) -> None:
        """Translate screen-style cancel/confirm into a bubbled selection."""
        self.post_message(StashPane.Selected(result))

    def _emit_result(self, result: StashRestoreResult | None = None) -> None:
        self.dismiss(result)

    def compose(self) -> ComposeResult:
        with Vertical(id="stash-pane-body"):
            yield from self._compose_stash_panels(with_chrome=False)

    def on_mount(self) -> None:
        self._on_stash_mount()

    def on_unmount(self) -> None:
        self._on_stash_unmount()

    def on_resize(self, event: events.Resize) -> None:
        self._on_stash_resize(event)


__all__ = [
    "DeleteRequested",
    "PinToggled",
    "STASH_BINDINGS",
    "StashControllerMixin",
    "StashPane",
    "StashRestoreResult",
]
