"""Prompt history selection modal with filtering for sase's TUI."""

from textual.app import ComposeResult
from textual.screen import ModalScreen

from sase.core.prompt_history_filter_wire import PromptHistorySeed

from ._prompt_history_interactions import PromptHistoryInteractionMixin
from ._prompt_history_list_state import PromptHistoryListStateMixin
from ._prompt_history_models import (
    PromptDisplayItem,
    PromptHistoryAction,
    PromptHistoryResult,
)
from ._prompt_history_rows import (
    _FALLBACK_PREVIEW_WIDTH,
    _MIN_PREVIEW_WIDTH,
    _OPTION_HORIZONTAL_PADDING_WIDTH,
    _PROMPT_COL_START,
    ellipsize_right as _ellipsize_right,
    format_history_timestamp as _format_history_timestamp,
    prompt_history_header_text as _prompt_history_header_text,
    prompt_preview_width_for_list_content as _prompt_preview_width_for_list_content,
)
from sase.history.prompt import PromptHistoryPageCursor
from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog

from .base import OptionListNavigationMixin
from .history_pane import (
    HISTORY_BINDINGS,
    HistoryPane,
    PromptHistoryControllerMixin,
    PromptHistoryLoadedPage,
    create_prompt_history_label,
)

_PromptDisplayItem = PromptDisplayItem

# Pre-extraction private aliases kept resolvable from this module for existing
# tests and the lazy export table.
_PromptHistoryLoadedPage = PromptHistoryLoadedPage
_create_prompt_history_label = create_prompt_history_label

# Re-exported for the pre-extraction import sites (tests and the lazy export
# table resolve these names from this module).
__all__ = [
    "PromptHistoryModal",
]


class PromptHistoryModal(
    PromptHistoryControllerMixin,
    PromptHistoryListStateMixin,
    PromptHistoryInteractionMixin,
    OptionListNavigationMixin,
    ModalScreen[PromptHistoryResult | None],
):
    """Modal for selecting a prompt from history with filtering and preview.

    The filter/list state and interactions live in the shared controller and
    history mixins (see :mod:`sase.ace.tui.modals.history_pane`) so the
    tabbed Prompts overlay reuses them without behavior drift; this screen
    only hosts the full modal body and dismisses with its outcome.
    """

    BINDINGS = HISTORY_BINDINGS

    def __init__(
        self,
        show_cancelled: bool = False,
        initial_filter: str = "",
        prompt_seed: str | None = None,
    ) -> None:
        """Initialize the prompt history modal.

        Args:
            show_cancelled: Whether to show cancelled prompts by default.
            initial_filter: An already-authored query to pre-fill in the
                modal filter.
            prompt_seed: An unauthored prompt draft (Ctrl+K) resolved into
                the initial ``project:`` + text query asynchronously, once
                the project-identity snapshot loads. Mutually exclusive with
                *initial_filter*.
        """
        super().__init__()
        self._init_history_controller(
            show_cancelled=show_cancelled,
            initial_filter=initial_filter,
            prompt_seed=prompt_seed,
        )

    def _emit_result(self, result: PromptHistoryResult | None = None) -> None:
        self.dismiss(result)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        yield from self._compose_history_modal_body()

    def on_mount(self) -> None:
        """Focus immediately and load identity + the first page outside the pump."""
        self._on_history_mount()


# Keep pre-extraction names resolvable from this module: the lazy export
# table, the type stubs, and existing tests import them from here.
_PROMPT_HISTORY_REEXPORTS = (
    PromptHistoryAction,
    PromptHistoryResult,
    PromptHistoryProjectCatalog,
    PromptHistorySeed,
    PromptHistoryPageCursor,
    HistoryPane,
    _FALLBACK_PREVIEW_WIDTH,
    _MIN_PREVIEW_WIDTH,
    _OPTION_HORIZONTAL_PADDING_WIDTH,
    _PROMPT_COL_START,
    _PromptHistoryLoadedPage,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
    _prompt_history_header_text,
    _prompt_preview_width_for_list_content,
)
