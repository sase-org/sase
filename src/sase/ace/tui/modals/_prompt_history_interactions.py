"""Key, selection, and preview interactions for the prompt history modal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import events
from textual.widgets import Input, OptionList, Static

from sase.history.prompt_metadata import summarize_prompt_for_preview

from ._prompt_history_models import (
    PromptDisplayItem,
    PromptHistoryAction,
    PromptHistoryResult,
    display_text_for_item,
)
from ._prompt_history_preview import build_prompt_history_metadata
from .base import FilterInput

if TYPE_CHECKING:
    from textual.app import App
    from textual.await_complete import AwaitComplete
    from textual.widget import Widget as _MixinBase

else:
    _MixinBase = object


class PromptHistoryInteractionMixin(_MixinBase):
    """Keyboard actions, row-selection handlers, and preview updates."""

    if TYPE_CHECKING:
        _filter_edit_generation: int
        _filtered_items: list[PromptDisplayItem]
        _show_cancelled: bool
        app: App[object]

        def action_load_more(self) -> None: ...

        def action_unload(self) -> None: ...

        def dismiss(self, result: Any = None) -> AwaitComplete: ...

        def _get_filtered_items(self, filter_text: str) -> list[PromptDisplayItem]: ...

        def _get_selected_prompt_text(self) -> str | None: ...

        def _refresh_options(self, *, preserve_highlight: bool = False) -> None: ...

        def _update_history_count_label(self) -> None: ...

        def _update_scope_hint(self) -> None: ...

    def on_key(self, event: events.Key) -> None:
        """Intercept keys that focused widgets consume before bindings.

        - Tab/Ctrl+I: Textual's focus cycling intercepts Tab before bindings.
        - Ctrl+J / Ctrl+K: intercepted while the filter input is focused so
          the keys page history here instead of bubbling to the app-level
          metadata-section bindings.
        - Ctrl+X: Input widget's built-in "cut" binding consumes it.
        """
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.action_load_to_input()
        elif event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.action_load_more()
        elif event.key == "ctrl+k":
            event.prevent_default()
            event.stop()
            self.action_unload()
        elif event.key == "ctrl+x":
            event.prevent_default()
            event.stop()
            self.action_toggle_cancelled()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change - update the option list."""
        self._filter_edit_generation += 1
        self._filtered_items = self._get_filtered_items(event.value)
        self._update_history_count_label()
        self._update_scope_hint()
        self._refresh_options()
        # Update preview for first filtered item
        if self._filtered_items:
            self._update_preview(self._filtered_items[0])
        else:
            self._clear_preview()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Handle Enter key in input - select and submit directly."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.SUBMIT,
                    prompt_text=prompt_text,
                )
            )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update preview when highlighting changes."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._filtered_items):
                self._update_preview(self._filtered_items[idx])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (click/double-click) - submit directly."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._filtered_items):
                self.dismiss(
                    PromptHistoryResult(
                        action=PromptHistoryAction.SUBMIT,
                        prompt_text=display_text_for_item(self._filtered_items[idx]),
                    )
                )

    def action_edit_first(self) -> None:
        """Handle Ctrl+G - select and open in editor first."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.EDIT_FIRST,
                    prompt_text=prompt_text,
                )
            )

    def action_toggle_cancelled(self) -> None:
        """Handle Ctrl+X - toggle visibility of cancelled prompts."""
        self._show_cancelled = not self._show_cancelled
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        self._filtered_items = self._get_filtered_items(filter_input.value)
        self._update_history_count_label()
        self._refresh_options()
        if self._filtered_items:
            self._update_preview(self._filtered_items[0])
        else:
            self._clear_preview()

    def action_load_to_input(self) -> None:
        """Handle Ctrl+I - load selected prompt into prompt input widget."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            self.dismiss(
                PromptHistoryResult(
                    action=PromptHistoryAction.LOAD,
                    prompt_text=prompt_text,
                )
            )

    def action_copy_and_cancel(self) -> None:
        """Handle Ctrl+Y - copy selected prompt to clipboard and dismiss."""
        prompt_text = self._get_selected_prompt_text()
        if prompt_text:
            from sase.ace.tui.actions.clipboard import schedule_copy_delivery

            schedule_copy_delivery(
                self.app,
                prompt_text,
                copied_label="prompt",
                task_name="sase-copy-prompt-history",
            )
        self.dismiss(None)

    def _update_preview(self, item: PromptDisplayItem) -> None:
        """Update preview panel with full prompt and metadata."""
        try:
            preview = self.query_one("#prompt-history-preview", Static)
            metadata = self.query_one("#prompt-history-metadata", Static)

            preview.update(display_text_for_item(item))
            metadata.update(
                build_prompt_history_metadata(
                    item,
                    summarize_for_preview=summarize_prompt_for_preview,
                )
            )

        except Exception:
            pass

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        try:
            preview = self.query_one("#prompt-history-preview", Static)
            metadata = self.query_one("#prompt-history-metadata", Static)
            preview.update("")
            metadata.update("")
        except Exception:
            pass


__all__ = ["PromptHistoryInteractionMixin"]
