"""List, filter, and scope-hint state for the prompt history modal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.history.prompt_history_project_filter import (
    filtered_prompt_history_row_indices,
)

from ._prompt_history_models import PromptDisplayItem, display_text_for_item
from ._prompt_history_rows import (
    _FALLBACK_PREVIEW_WIDTH,
    prompt_preview_width_for_list_content,
)
from .base import FilterInput

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.core.prompt_history_filter_wire import (
        CompiledPromptHistoryQuery,
        PromptHistoryRowFacts,
        PromptHistorySeed,
    )
    from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog
else:
    _MixinBase = object


class PromptHistoryListStateMixin(_MixinBase):
    """Filtering, option rebuilding, and list-pane labels."""

    if TYPE_CHECKING:
        _all_items: list[PromptDisplayItem]
        _catalog: PromptHistoryProjectCatalog | None
        _filtered_items: list[PromptDisplayItem]
        _history_exhausted: bool
        _history_loaded_once: bool
        _history_loading: bool
        _last_compiled_query: CompiledPromptHistoryQuery | None
        _last_preview_width_budget: int
        _row_facts: list[PromptHistoryRowFacts]
        _seed_applied_value: str | None
        _seed_hint_text: str | None
        _show_cancelled: bool

        def _clear_preview(self) -> None: ...

        def _create_styled_label(self, item: PromptDisplayItem) -> Text: ...

        def _resolved_page_size(self) -> int: ...

        def _update_preview(self, item: PromptDisplayItem) -> None: ...

    @staticmethod
    def _default_scope_hint_text() -> Text:
        """Return the muted default hint teaching the ``project:`` grammar."""
        return Text(
            "Type project:<name> text to scope results to one project.",
            style="dim",
        )

    def _update_scope_hint(self) -> None:
        """Refresh the helper line beneath the filter input from the last query."""
        try:
            widget = self.query_one("#prompt-history-scope-hint", Static)
        except Exception:
            return

        widget.remove_class("-error")
        widget.remove_class("-scoped")
        query = self._last_compiled_query

        if query is not None and (not query.valid or query.diagnostic):
            widget.update(
                query.diagnostic or "Project filter needs a value after project:."
            )
            widget.add_class("-error")
            return

        if query is not None and query.raw_project_value is not None:
            label = query.project_label or query.raw_project_value
            text = Text(f"Project: {label}")
            text.append(
                "  ·  Remove the project filter to search all loaded prompts",
                style="dim",
            )
            widget.update(text)
            widget.add_class("-scoped")
            return

        try:
            filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
            current_value: str | None = filter_input.value
        except Exception:
            current_value = None

        if (
            self._seed_hint_text is not None
            and current_value is not None
            and current_value == self._seed_applied_value
        ):
            widget.update(Text(self._seed_hint_text, style="dim"))
            return

        widget.update(self._default_scope_hint_text())

    def _apply_seed(self, seed: PromptHistorySeed) -> None:
        """Pre-fill the filter input from a resolved Ctrl+K prompt seed."""
        filter_input = self.query_one("#prompt-history-filter-input", FilterInput)
        filter_input.value = seed.seed_text
        filter_input.cursor_position = len(seed.seed_text)
        self._seed_hint_text = seed.hint
        self._seed_applied_value = seed.seed_text

    def _hints_text(self) -> str:
        """Return the footer hint line using the configured page size."""
        page_size = self._resolved_page_size()
        return (
            f"j/k ^n/^p • ^j/+{page_size} ^k/-{page_size} • Enter: submit • "
            "^g: edit • ^i: load • ^x: cancelled • ^y: copy • Esc/q: cancel"
        )

    def _create_initial_options(self) -> list[Option]:
        """Return initial rows, including a loading row before disk data lands."""
        options = self._create_options(self._filtered_items)
        if options or self._history_loaded_once:
            return options
        return [self._loading_option()]

    @staticmethod
    def _loading_option() -> Option:
        """Return the disabled placeholder shown during the initial page load."""
        return Option(Text("Loading prompt history...", style="dim"), disabled=True)

    def _empty_result_option(self) -> Option:
        """Return the disabled placeholder shown for a loaded-but-empty result."""
        if self._history_exhausted:
            message = "No matching prompts"
        else:
            message = (
                f"No matches in loaded prompts · ^j +{self._resolved_page_size()}"
                " older · remove the project filter to search all loaded prompts"
            )
        return Option(Text(message, style="dim"), disabled=True)

    def _create_options(
        self,
        items: list[PromptDisplayItem],
        *,
        preview_width: int | None = None,
    ) -> list[Option]:
        """Create options from prompt items."""
        self._last_preview_width_budget = (
            self._resolve_preview_width_budget()
            if preview_width is None
            else preview_width
        )
        return [
            Option(self._create_styled_label(item), id=str(i))
            for i, item in enumerate(items)
        ]

    def _resolve_preview_width_budget(self) -> int:
        """Return the current prompt preview width budget for list rows."""
        try:
            option_list = self.query_one("#prompt-history-list", OptionList)
        except Exception:
            return _FALLBACK_PREVIEW_WIDTH

        list_content_width = option_list.scrollable_content_region.width
        if list_content_width <= 0:
            list_content_width = option_list.content_size.width
        if list_content_width <= 0:
            list_content_width = option_list.size.width
        return prompt_preview_width_for_list_content(list_content_width)

    def _refresh_options(
        self,
        *,
        preserve_highlight: bool = False,
        preview_width: int | None = None,
    ) -> None:
        """Rebuild visible options using one shared preview-width budget."""
        option_list = self.query_one("#prompt-history-list", OptionList)
        highlighted = option_list.highlighted if preserve_highlight else None
        option_list.clear_options()
        option_list.add_options(
            self._create_options(
                self._filtered_items,
                preview_width=preview_width,
            )
        )
        if not self._filtered_items:
            if not self._history_loaded_once:
                option_list.add_option(self._loading_option())
            else:
                option_list.add_option(self._empty_result_option())
            return
        if preserve_highlight and highlighted is not None:
            option_list.highlighted = min(highlighted, len(self._filtered_items) - 1)
        elif not preserve_highlight:
            option_list.highlighted = 0

    def _refresh_options_for_current_width(self) -> None:
        """Refresh option labels if layout gives the preview column a new width."""
        if not self._all_items:
            return
        preview_width = self._resolve_preview_width_budget()
        if preview_width == self._last_preview_width_budget:
            return
        self._refresh_options(preserve_highlight=True, preview_width=preview_width)

    def _history_count_label(self) -> str:
        """Return the live list-pane history count label."""
        history_loading = getattr(self, "_history_loading", False)
        history_loaded_once = getattr(self, "_history_loaded_once", True)
        history_exhausted = getattr(self, "_history_exhausted", True)
        if history_loading and not history_loaded_once:
            return "History · loading..."
        loaded = len(self._all_items)
        visible = len(self._filtered_items)
        if not history_loaded_once:
            return "History · loading..."
        if history_exhausted:
            return f"History · {visible:,} / {loaded:,} total"
        suffix = f" · ^j +{self._resolved_page_size()} older"
        if history_loading:
            suffix = " · loading older..."
        return f"History · {visible:,} / {loaded:,} loaded{suffix}"

    def _update_history_count_label(self) -> None:
        """Update the list-pane count label if it is mounted."""
        try:
            label = self.query_one("#prompt-history-list-label", Label)
        except Exception:
            return
        label.update(self._history_count_label())

    def _get_filtered_items(self, filter_text: str) -> list[PromptDisplayItem]:
        """Get items that match the filter text, honoring a ``project:`` scope.

        A malformed qualifier (``self._last_compiled_query.valid`` is
        ``False``) selects nothing until it is fixed, so submit/edit/load/copy
        never act on a stale selection.
        """
        catalog = getattr(self, "_catalog", None)
        if catalog is None:
            # A fast keystroke landing before the identity snapshot loads (or
            # a unit test built via ``object.__new__``, bypassing __init__):
            # degrade to the legacy substring behavior rather than block.
            self._last_compiled_query = None
            if not filter_text:
                if self._show_cancelled:
                    return self._all_items.copy()
                return [item for item in self._all_items if not item.entry.cancelled]
            filter_lower = filter_text.lower()
            return [
                item
                for item in self._all_items
                if (self._show_cancelled or not item.entry.cancelled)
                and (
                    filter_lower in display_text_for_item(item).lower()
                    or filter_lower in item.entry.text.lower()
                )
            ]

        compiled = catalog.compile_query(filter_text)
        self._last_compiled_query = compiled
        if not compiled.valid:
            return []

        matched_indices = filtered_prompt_history_row_indices(compiled, self._row_facts)
        return [
            item
            for idx, item in enumerate(self._all_items)
            if idx in matched_indices
            and (self._show_cancelled or not item.entry.cancelled)
        ]

    def _get_selected_prompt_text(self) -> str | None:
        """Get the prompt text for the currently highlighted item."""
        if not self._filtered_items:
            return None
        option_list = self.query_one("#prompt-history-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self._filtered_items):
            return display_text_for_item(self._filtered_items[highlighted])
        return display_text_for_item(self._filtered_items[0])

    def on_resize(self, _event: events.Resize) -> None:
        """Recompute adaptive row widths after terminal resize/layout changes."""
        if self._all_items:
            self.call_after_refresh(self._refresh_options_for_current_width)


__all__ = ["PromptHistoryListStateMixin"]
