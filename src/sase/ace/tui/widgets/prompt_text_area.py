"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import TextArea

from sase.ace.tui.widgets._alt_syntax_highlight import AltSyntaxHighlightMixin
from sase.ace.tui.widgets._file_completion import FileCompletionMixin
from sase.ace.tui.widgets._jinja_diagnostics import JinjaDiagnosticsMixin
from sase.ace.tui.widgets._jinja_highlight import JinjaHighlightMixin
from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._prompt_soft_completion import PromptSoftCompletionMixin
from sase.ace.tui.widgets._prompt_text_area_actions import (
    PromptTextAreaActionsMixin,
)
from sase.ace.tui.widgets._prompt_text_area_key_handling import (
    PromptTextAreaKeyHandlingMixin,
)
from sase.ace.tui.widgets._prompt_search import PromptSearchMixin
from sase.ace.tui.widgets._search_highlight import SearchHighlightMixin
from sase.ace.tui.widgets._snippets import SnippetExpansionMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets._vim_registers import VimRegister
from sase.ace.tui.widgets._vcs_mru_cycling import (
    VcsMruCyclingMixin,
)
from sase.ace.tui.widgets._xprompt_arg_hints import XPromptArgHintMixin
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
)
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    PendingOptionalSpacer,
    XPromptAssistEntry,
    build_xprompt_assist_entries,
)
from sase.xprompt._parsing import (
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
)

if TYPE_CHECKING:
    from ..app import AceApp


__all__ = [
    "PromptTextArea",
    "build_xprompt_assist_entries",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
]


class PromptTextArea(
    PromptTextAreaKeyHandlingMixin,
    PromptTextAreaActionsMixin,
    JinjaDiagnosticsMixin,
    AltSyntaxHighlightMixin,
    SearchHighlightMixin,
    PromptSearchMixin,
    JinjaHighlightMixin,
    VimNormalModeMixin,
    FileCompletionMixin,
    PromptSoftCompletionMixin,
    XPromptArgHintMixin,
    SnippetExpansionMixin,
    VcsMruCyclingMixin,
    LineRenderingMixin,
    TextArea,
):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt, or opens the submit chooser for prompt stacks.
    Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    BINDINGS = [
        ("enter", "submit_prompt", "Submit"),
        ("ctrl+j", "insert_newline", "New line"),
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("alt+f", "cursor_word_right", "Forward word"),
        ("alt+b", "cursor_word_left", "Backward word"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._vim_mode: str = "insert"
        self._pending_keys: str = ""
        self._insert_g_prefix_pending: bool = False
        self._normal_g_prefix_pending: bool = False
        self._count_prefix: str = ""
        self._pending_count: int | None = None
        self._pending_operator: str = ""
        self._pending_operator_count: int = 1
        self._pending_surround_range: (
            tuple[str, tuple[int, int], tuple[int, int]] | None
        ) = None
        self._pending_change_surround_locations: (
            tuple[
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
            ]
            | None
        ) = None
        self._mutation_key_buffer: list[str] = []
        self._mutation_count: int = 1
        self._last_mutation_keys: list[str] = []
        self._last_mutation_count: int = 1
        self._last_mutation_insert: str | None = None
        self._last_visual_mutation: tuple[str, str, int, int] | None = None
        self._dot_insert_capture_offset: int | None = None
        self._replaying_dot: bool = False
        self._last_char_search: tuple[str, str] | None = None
        self._vim_register: VimRegister = VimRegister()
        self._visual_anchor: tuple[int, int] | None = None
        self._visual_cursor: tuple[int, int] | None = None
        self._snippet_tabstops: list[int] = []
        self._snippet_end_from_doc_end: int = 0
        self._file_completion_candidates: list[CompletionCandidate] = []
        self._file_completion_index: int = 0
        self._file_completion_active: bool = False
        self._completion_kind: str = "file"
        self._vcs_project_catalog_warmed: bool = False
        self._active_xprompt_arg_hint: ActiveXPromptArgHint | None = None
        self._pending_optional_spacer: PendingOptionalSpacer | None = None
        self._xprompt_arg_assist_entries_by_project: dict[
            str | None, list[XPromptAssistEntry]
        ] = {}
        self._xprompt_arg_assist_warming_projects: set[str | None] = set()
        self._xprompt_arg_assist_worker_projects: dict[str, str | None] = {}
        self._vcs_mru_index: int | None = None
        self._prompt_completion_generation: int = 0
        self._prompt_completion_timer: Any | None = None
        self._soft_completion: PromptSoftCompletion | None = None

    @property
    def _ace_app(self) -> AceApp:
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app

    def _absolute_offset(self, location: tuple[int, int]) -> int:
        """Convert a document location to an absolute character offset."""
        row, col = location
        return sum(len(self.document.get_line(r)) + 1 for r in range(row)) + col

    def _location_from_absolute(self, offset: int) -> tuple[int, int]:
        """Convert an absolute character offset to a document location."""
        remaining = max(0, offset)
        for row in range(self.document.line_count):
            line_len = len(self.document.get_line(row))
            if remaining <= line_len:
                return row, remaining
            remaining -= line_len + 1
        last_row = self.document.line_count - 1
        return last_row, len(self.document.get_line(last_row))
