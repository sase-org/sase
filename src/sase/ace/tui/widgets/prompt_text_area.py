"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._alt_syntax_highlight import AltSyntaxHighlightMixin
from sase.ace.tui.widgets._file_completion import FileCompletionMixin
from sase.ace.tui.widgets._jinja_diagnostics import JinjaDiagnosticsMixin
from sase.ace.tui.widgets._jinja_highlight import JinjaHighlightMixin
from sase.ace.tui.widgets._prompt_soft_completion import PromptSoftCompletionMixin
from sase.ace.tui.widgets._prompt_text_area_actions import (
    PromptTextAreaActionsMixin,
)
from sase.ace.tui.widgets._prompt_text_area_key_handling import (
    PromptTextAreaKeyHandlingMixin,
)
from sase.ace.tui.widgets._prompt_search import PromptSearchMixin
from sase.ace.tui.widgets._prompt_jump import PromptJumpMixin
from sase.ace.tui.widgets._prompt_preview import PromptPreviewMixin
from sase.ace.tui.widgets._search_highlight import SearchHighlightMixin
from sase.ace.tui.widgets._snippets import SnippetExpansionMixin
from sase.ace.tui.widgets._vcs_mru_cycling import (
    VcsMruCyclingMixin,
)
from sase.ace.tui.widgets._xprompt_arg_hints import XPromptArgHintMixin
from sase.ace.tui.widgets._xprompt_syntax_highlight import (
    XPromptSyntaxHighlightMixin,
)
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
)
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult
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
    from sase.ace.tui.agent_completion import AgentCompletionCandidate


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
    XPromptSyntaxHighlightMixin,
    PromptSearchMixin,
    PromptPreviewMixin,
    PromptJumpMixin,
    JinjaHighlightMixin,
    FileCompletionMixin,
    PromptSoftCompletionMixin,
    XPromptArgHintMixin,
    SnippetExpansionMixin,
    VcsMruCyclingMixin,
    VimTextArea,
):
    """Prompt-bar TextArea: the shared vim/readline layer plus prompt features.

    Builds on :class:`~sase.ace.tui.widgets.vim_text_area.VimTextArea` (vim
    normal/visual modes, motions, operators, readline insert keys) and adds the
    prompt-only surfaces -- completions, xprompt hints, snippets, search, and
    the ``PromptInputBar`` integration -- by overriding the base's host hooks.

    Enter submits the prompt, or opens the submit chooser for prompt stacks.
    Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    BINDINGS = [
        ("enter", "submit_prompt", "Submit"),
        ("ctrl+j", "insert_newline", "New line"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._insert_g_prefix_pending: bool = False
        self._normal_g_prefix_pending: bool = False
        self._snippet_tabstops: list[int] = []
        self._snippet_end_from_doc_end: int = 0
        self._file_completion_candidates: list[CompletionCandidate] = []
        self._file_completion_index: int = 0
        self._file_completion_active: bool = False
        self._completion_kind: str = "file"
        self._agent_completion_candidates: list[AgentCompletionCandidate] | None = None
        self._vcs_project_catalog_warmed: bool = False
        self._vcs_ref_completion_has_namespaces: bool = False
        self._vcs_repo_completion_key: tuple[str, str] | None = None
        self._vcs_repo_completion_result: VcsRepoFetchResult | None = None
        self._vcs_repo_completion_inflight: set[tuple[str, str]] = set()
        self._active_xprompt_arg_hint: ActiveXPromptArgHint | None = None
        self._pending_optional_spacer: PendingOptionalSpacer | None = None
        self._xprompt_arg_assist_entries_by_project: dict[
            str | None, list[XPromptAssistEntry]
        ] = {}
        self._xprompt_highlight_skill_entries: list[XPromptAssistEntry] | None = None
        self._xprompt_highlight_skill_names: frozenset[str] = frozenset()
        self._xprompt_arg_assist_warming_projects: set[str | None] = set()
        self._xprompt_arg_assist_worker_projects: dict[str, str | None] = {}
        self._vcs_mru_index: int | None = None
        self._prompt_completion_generation: int = 0
        self._prompt_completion_timer: Any | None = None
        self._soft_completion: PromptSoftCompletion | None = None
        self._prompt_preview_request_id: int = 0
        self._prompt_jump_request_id: int = 0

    @property
    def _ace_app(self) -> AceApp:
        """Get the app as AceApp type."""
        from ..app import AceApp

        assert isinstance(self.app, AceApp)
        return self.app
