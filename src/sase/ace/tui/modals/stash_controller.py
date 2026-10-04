"""Shared stash list/preview interactions.

This module owns :class:`StashControllerMixin`, the interaction, layout, and
confirm logic shared by the standalone :class:`StashedPromptsModal` and the
tabbed :class:`PromptsModal` overlay. Entry state and lifecycle repaints live
on its :class:`StashControllerStateMixin` base.
"""

from __future__ import annotations

from dataclasses import replace

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.macro_syntax import highlight_prompt_text
from sase.core.prompt_stash_wire import PromptStashEntryWire

from ._prompt_stash_preview import PromptStashPreviewPane, tagified_stash_text
from ._stash_controller_state import StashControllerStateMixin
from .prompt_stash_row import (
    DEFAULT_STASH_PREVIEW_WIDTH,
    INDEX_KEYS,
    PIN_GLYPH,
    append_shortcut,
    prompt_stash_preview_width_for_list_content,
    stash_row_age,
    stash_row_label,
)
from .stash_messages import (
    DeleteRequested,
    PinToggled,
    StashRestoreResult,
    TrashRequested,
    newest_first_stash_entries,
    single_restore_result,
)

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


class StashControllerMixin(StashControllerStateMixin):
    """Shared stash list/preview state and interactions.

    Hosts (the standalone modal and the overlay pane) provide ``_emit_result``
    and compose the shared pieces. ``_option_list_id`` must name the stash
    ``OptionList`` DOM id on the host.
    """

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
            self._show_placeholder()
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
        if self._trash_mode():
            return (
                "1-9/0 restore · a all · j/k move · enter · esc/q · ^d/u\n"
                f"space {PIN_GLYPH} pin · tab ✓ · d trash row · D trash all"
            )
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
            self._show_placeholder()
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
        return single_restore_result(entry, pinned=entry.id in self._pinned)

    def newest_restore_result(self) -> StashRestoreResult | None:
        """Return the restore outcome for the newest stash entry.

        Newest-first is ``(created_at, pane_index)`` order, pin-aware, and
        ignores staged marks like digit keys do. Returns ``None`` when the
        stash is empty.
        """
        if not self._entries:
            return None
        newest = newest_first_stash_entries(list(self._entries))[0]
        return single_restore_result(newest, pinned=newest.id in self._pinned)

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
        discard_ids = [e.id for e in self._entries if e.id in self._deleted]
        # In trash mode delete marks mean Trash (the host confirms, applies
        # through Rust, and repaints authoritatively); with a zero limit, or
        # in the standalone picker, they stay permanent deletions.
        trash_mode = self._trash_mode()
        delete_ids = [] if trash_mode else list(discard_ids)
        trash_ids = list(discard_ids) if trash_mode else []
        if not marked and discard_ids and len(discard_ids) < len(self._entries):
            if trash_mode:
                # Pending state: keep rows and marks; the host confirms and
                # repaints from the store outcome (success or failure).
                self.post_message(TrashRequested(list(discard_ids)))  # type: ignore[attr-defined]
                return
            self._apply_deletions_in_place(delete_ids)
            return
        if not marked and not discard_ids:
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
                trash_ids=trash_ids,
            )
        )

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        # ``enter`` (and click) confirms: restore the toggled set, or just the
        # highlighted row when nothing is toggled.
        self.action_confirm()
