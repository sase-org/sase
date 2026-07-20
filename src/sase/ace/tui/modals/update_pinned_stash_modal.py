"""Picker for choosing which pinned prompt stash to update."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.xprompt_syntax import highlight_prompt_text
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.project_display_names import ProjectDisplaySnapshot

from ._prompt_stash_preview import PromptStashPreviewPane
from .base import OptionListNavigationMixin
from .prompt_stash_row import (
    DEFAULT_STASH_PREVIEW_WIDTH,
    INDEX_KEYS,
    append_shortcut,
    prompt_stash_preview_width_for_list_content,
    stash_row_age,
    stash_row_label,
    stash_row_prompt_count,
)

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


class UpdatePinnedStashModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Single-select picker for the pinned prompt stash to overwrite."""

    _option_list_id = "update-pinned-stash-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("ctrl+d", "scroll_preview_down", "Preview Down", priority=True),
        Binding("ctrl+u", "scroll_preview_up", "Preview Up", priority=True),
        *[
            Binding(key, f"pick_index({idx})", f"Pick #{idx + 1}", show=False)
            for idx, key in enumerate(INDEX_KEYS)
        ],
    ]

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
    ) -> None:
        super().__init__()
        self._entries: list[PromptStashEntryWire] = sorted(
            entries,
            key=lambda e: (e.created_at, e.pane_index),
            reverse=True,
        )
        self._project_display_snapshot = (
            project_display_snapshot or ProjectDisplaySnapshot()
        )
        self._prompt_counts = {
            entry.id: stash_row_prompt_count(entry) for entry in self._entries
        }
        self._highlight_cache: dict[str, Text] = {}
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._refreshing_options = False
        self._narrow = True
        self._last_preview_width_budget = DEFAULT_STASH_PREVIEW_WIDTH

    def compose(self) -> ComposeResult:
        with Container(id="update-pinned-stash-container"):
            with Horizontal(id="update-pinned-stash-panels"):
                with Vertical(id="update-pinned-stash-list-panel"):
                    yield Label("Update pinned prompt", id="update-pinned-stash-title")
                    yield OptionList(
                        *self._build_options(), id="update-pinned-stash-list"
                    )
                    yield Static(self._hint_text(), id="update-pinned-stash-hints")
                yield PromptStashPreviewPane(id="update-pinned-stash-preview-pane")

    def on_mount(self) -> None:
        self._preview_debouncer = DetailPanelDebouncer(self.app)
        self._set_narrow_mode(self.app.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        try:
            self.query_one("#update-pinned-stash-list", OptionList).focus()
        except Exception:
            pass
        if self._entries:
            self._paint_preview(self._entries[0].id)
        else:
            self.query_one(PromptStashPreviewPane).show_placeholder()
        self.call_after_refresh(self._refresh_rows_for_current_width)

    def on_unmount(self) -> None:
        if self._preview_debouncer is not None:
            self._preview_debouncer.cancel()

    def on_resize(self, event: events.Resize) -> None:
        self._set_narrow_mode(event.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        self.call_after_refresh(self._refresh_rows_for_current_width)

    def _hint_text(self) -> str:
        return (
            "1-9 0 update · j/k navigate · enter confirm\nesc/q cancel · ^d/^u preview"
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
                    marked_for_pop=False,
                    marked_for_delete=False,
                    pinned=True,
                    age=stash_row_age(entry),
                    prompt_count=self._prompt_counts[entry.id],
                    preview_width=preview_width,
                    project_display_snapshot=self._project_display_snapshot,
                )
            )
            options.append(Option(label, id=str(idx)))
        return options

    def _resolve_preview_width_budget(self) -> int:
        if self._narrow:
            return DEFAULT_STASH_PREVIEW_WIDTH
        try:
            option_list = self.query_one("#update-pinned-stash-list", OptionList)
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
        try:
            option_list = self.query_one("#update-pinned-stash-list", OptionList)
        except Exception:
            return
        highlighted = option_list.highlighted
        self._refreshing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(self._build_options(preview_width=preview_width))
            if self._entries and highlighted is not None:
                option_list.highlighted = min(highlighted, len(self._entries) - 1)
        finally:
            self._refreshing_options = False

    def _set_narrow_mode(self, narrow: bool) -> None:
        self._narrow = narrow
        try:
            container = self.query_one("#update-pinned-stash-container", Container)
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
            self.query_one(PromptStashPreviewPane).show_placeholder()
            return
        highlighted = self._highlight_cache.get(entry.id)
        if highlighted is None:
            highlighted = highlight_prompt_text(entry.text)
            self._highlight_cache[entry.id] = highlighted
        self.query_one(PromptStashPreviewPane).show_entry(
            entry,
            prompt_count=self._prompt_counts[entry.id],
            highlighted_body=highlighted,
            project_display_snapshot=self._project_display_snapshot,
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._refreshing_options or event.option is None or event.option.id is None:
            return
        try:
            index = int(event.option.id)
        except ValueError:
            return
        if 0 <= index < len(self._entries):
            self._schedule_preview(self._entries[index].id)

    def action_scroll_preview_down(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(1)

    def action_scroll_preview_up(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(-1)

    def _highlighted_entry(self) -> PromptStashEntryWire | None:
        try:
            option_list = self.query_one("#update-pinned-stash-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._entries):
            return None
        return self._entries[highlighted]

    def action_pick_index(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            return
        self.dismiss(self._entries[index].id)

    def action_confirm(self) -> None:
        entry = self._highlighted_entry()
        self.dismiss(entry.id if entry is not None else None)

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_confirm()


__all__ = ["UpdatePinnedStashModal"]
