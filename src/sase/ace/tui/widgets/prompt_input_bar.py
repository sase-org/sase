"""Prompt input bar widget for agent workflow in the ace TUI."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_actions import (
    PromptInputBarActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_completion import (
    PromptInputBarCompletionMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_dispatch import (
    PromptInputBarDispatchMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_frontmatter import (
    InlineExpansionTransaction,
    PromptInputBarFrontmatterMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_hints import (
    PromptInputBarGPrefixHintsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_lifecycle import (
    PromptInputBarLifecycleMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_mini_xprompt_pane import (
    PromptInputBarMiniXPromptPaneMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_messages import (
    AllEditorRequested as _AllEditorRequested,
    Cancelled as _Cancelled,
    EditorRequested as _EditorRequested,
    GlossaryPanelRequested as _GlossaryPanelRequested,
    HistoryRequested as _HistoryRequested,
    MemoryPanelRequested as _MemoryPanelRequested,
    MiniXPromptPaneSaveRequested as _MiniXPromptPaneSaveRequested,
    MiniXPromptTargetRequested as _MiniXPromptTargetRequested,
    SnippetPanelRequested as _SnippetPanelRequested,
    RestoreRequested as _RestoreRequested,
    SaveAsXpromptRequested as _SaveAsXpromptRequested,
    SnippetPaneSaveRequested as _SnippetPaneSaveRequested,
    SnippetRequested as _SnippetRequested,
    SnippetTargetRequested as _SnippetTargetRequested,
    Stashed as _Stashed,
    Submitted as _Submitted,
    UpdatePinnedRequested as _UpdatePinnedRequested,
    WorkflowEditorRequested as _WorkflowEditorRequested,
    WriteXpromptRequested as _WriteXpromptRequested,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    PromptInputBarStackActionsMixin,
    StashedPromptPane,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_rendering import (
    PromptInputBarStackRenderingMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_search import (
    PromptInputBarSearchMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_snippet_pane import (
    PromptInputBarSnippetPaneMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_status import (
    PromptInputBarStatusMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_subtitles import (
    PromptInputBarSubtitlesMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_title import (
    PromptInputBarTitleMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets.prompt_stack import (
    PromptStackState,
    XPromptReadonlyTarget,
)
from sase.xprompt.models import InputArg

__all__ = ["PromptInputBar", "StashedPromptPane"]


class PromptInputBar(
    PromptInputBarLifecycleMixin,
    PromptInputBarTitleMixin,
    PromptInputBarStatusMixin,
    PromptInputBarSubtitlesMixin,
    PromptInputBarFrontmatterMixin,
    PromptInputBarSnippetPaneMixin,
    PromptInputBarMiniXPromptPaneMixin,
    PromptInputBarStackActionsMixin,
    PromptInputBarGPrefixHintsMixin,
    PromptInputBarSearchMixin,
    PromptInputBarDispatchMixin,
    PromptInputBarActionsMixin,
    PromptInputBarCompletionMixin,
    PromptInputBarStackRenderingMixin,
    Static,
):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    Submitted = _Submitted
    Cancelled = _Cancelled
    Stashed = _Stashed
    RestoreRequested = _RestoreRequested
    GlossaryPanelRequested = _GlossaryPanelRequested
    MemoryPanelRequested = _MemoryPanelRequested
    SnippetPanelRequested = _SnippetPanelRequested
    UpdatePinnedRequested = _UpdatePinnedRequested
    SaveAsXpromptRequested = _SaveAsXpromptRequested
    EditorRequested = _EditorRequested
    AllEditorRequested = _AllEditorRequested
    HistoryRequested = _HistoryRequested
    SnippetRequested = _SnippetRequested
    SnippetTargetRequested = _SnippetTargetRequested
    SnippetPaneSaveRequested = _SnippetPaneSaveRequested
    MiniXPromptTargetRequested = _MiniXPromptTargetRequested
    MiniXPromptPaneSaveRequested = _MiniXPromptPaneSaveRequested
    WorkflowEditorRequested = _WorkflowEditorRequested
    WriteXpromptRequested = _WriteXpromptRequested

    BINDINGS = []  # type: ignore[assignment]

    def __init__(
        self,
        initial_value: str = "",
        mode: str = "prompt",
        *,
        initial_panes: list[str] | None = None,
        initial_xprompt_markdown: str | None = None,
        initial_selected_pane: int | None = None,
        initial_cursor: tuple[int, int] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value
        self._mode = mode
        self._initial_cursor = initial_cursor
        self._completion_visible = False
        self._completion_line_count = 0
        self._completion_panel_kind: str | None = None
        self._g_prefix_hints_visible = False
        self._g_prefix_hints_line_count = 0
        self._g_prefix_hints_signature: tuple[
            str, tuple[tuple[str, tuple[str, ...], str], ...]
        ] = ("", ())
        self._dispatch_context_visible = False
        self._dispatch_context_line_count = 0
        self._dispatch_catalog_loaded = False
        self._dispatch_catalog_loading = False
        self._dispatch_target_rows: dict[str, dict[str, object]] = {}
        self._dispatch_preflight_override: tuple[str, str, str] | None = None
        self._search_command_visible = False
        self._search_command_line_count = 0
        self._mode_subtitle = "[Enter] send  [Esc] normal  [^C] cancel"
        self._subtitle_base = self._mode_subtitle
        self._soft_completion_visible = False
        self._title_mode_suffix = ""
        self._readonly_xprompt_target: XPromptReadonlyTarget | None = None
        self._xprompt_source_stale = False
        self._xprompt_stale_check_in_flight = False
        self._xprompt_stale_checked_mono = 0.0
        self._xprompt_target_generation = 0
        # Monotonic per-rebuild id namespace so a fresh stack mounted while the
        # previous panes are still being detached never collides on widget ids.
        self._generation = 0
        self._snippet_focus_restore: PromptFocusRestore | None = None
        self._mini_xprompt_focus_restore: PromptFocusRestore | None = None
        self._placeholder = ""
        # ``#@`` + ``Ctrl+I`` inline expansions that auto-staged xprompt inputs,
        # coupled to the body splice so NORMAL-mode ``u`` / ``Ctrl+R`` unstage /
        # restage them. ``_auto_staged_inputs`` maps a currently auto-owned input
        # name to its persisted declaration (to detect later user edits).
        self._inline_expansion_txns: list[InlineExpansionTransaction] = []
        self._auto_staged_inputs: dict[str, InputArg] = {}
        if initial_panes is not None:
            # Explicit pane seeding: one verbatim pane per entry, never split on
            # an embedded ``---`` or lifted frontmatter. Used by bulk
            # kill-and-edit so each killed agent maps to exactly one pane.
            self._stack = PromptStackState.from_panes(initial_panes)
        elif initial_xprompt_markdown is not None:
            # Editor-file semantics: lift leading xprompt frontmatter into the
            # shared stack frontmatter and split real ``---`` body separators
            # into one pane per agent segment. Used when a ` @`-review-marker
            # editor return remounts the bar for review (frontmatter auto-shows
            # on mount). Compared with ``initial_value`` history-load semantics,
            # this path also normalizes a lone body pane through the canonical
            # splitter instead of keeping the body text verbatim.
            self._stack = PromptStackState.from_text(initial_xprompt_markdown)
        else:
            self._stack = self._state_from_text(initial_value)
        if initial_selected_pane is not None:
            self._stack.focus(initial_selected_pane)
        self._frontmatter_return_index = self._stack.selected_index
        self._todo_counts_by_item_id: dict[str, int] = {}
        self._sync_todo_counts_from_stack()
