"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key
from textual.screen import ModalScreen
from textual.worker import WorkerState
from textual.widgets import TextArea

from sase.ace.tui.widgets._file_completion import FileCompletionMixin
from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._snippets import SnippetExpansionMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    extract_token_around_cursor,
)
from sase.ace.tui.widgets.prompt_completion import (
    DEFAULT_PROMPT_COMPLETION_SETTINGS,
    PromptCompletionSettings,
    PromptSoftCompletion,
    build_prompt_soft_completion,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    accepted_xprompt_arg_hint,
    build_xprompt_assist_entries,
    detect_xprompt_arg_hint_at_cursor,
    named_args_skeleton,
    xprompt_completion_skeleton,
)
from sase.ace.tui.widgets.xprompt_completion import is_xprompt_like_token
from sase.xprompt._parsing import (
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    from ..app import AceApp


def _prompt_bar_class() -> type[PromptInputBar]:
    """Lazy import to avoid circular dependency with prompt_input_bar."""
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

    return PromptInputBar


class PromptTextArea(
    VimNormalModeMixin,
    FileCompletionMixin,
    SnippetExpansionMixin,
    LineRenderingMixin,
    TextArea,
):
    """Custom TextArea with multiline support and readline-style keybindings.

    Enter submits the prompt. Ctrl+J inserts a newline.
    Line numbers appear automatically when there's more than one line.
    """

    BINDINGS = [
        ("enter", "submit_prompt", "Submit"),
        ("ctrl+j", "insert_newline", "New line"),
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("alt+f", "cursor_word_right", "Forward word"),
        ("alt+b", "cursor_word_left", "Backward word"),
        ("ctrl+g", "open_editor", "Edit in editor"),
        ("ctrl+y", "open_workflow_editor", "Workflow YAML"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._vim_mode: str = "insert"
        self._pending_keys: str = ""
        self._count_prefix: str = ""
        self._pending_count: int | None = None
        self._pending_operator: str = ""
        self._pending_operator_count: int = 1
        self._mutation_key_buffer: list[str] = []
        self._last_mutation_keys: list[str] = []
        self._replaying_dot: bool = False
        self._last_char_search: tuple[str, str] | None = None
        self._snippet_tabstops: list[int] = []
        self._snippet_end_from_doc_end: int = 0
        self._file_completion_candidates: list[CompletionCandidate] = []
        self._file_completion_index: int = 0
        self._file_completion_active: bool = False
        self._completion_kind: str = "file"
        self._active_xprompt_arg_hint: ActiveXPromptArgHint | None = None
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

    def _find_prompt_bar(self) -> Any:
        """Walk up the widget tree to find the parent PromptInputBar."""
        PromptInputBar = _prompt_bar_class()
        parent = self.parent
        while parent is not None:
            if isinstance(parent, PromptInputBar):
                return parent
            parent = parent.parent
        return None

    def action_submit_prompt(self) -> None:
        """Submit the prompt text."""
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_insert_newline(self) -> None:
        """Insert a newline at the cursor position."""
        start, end = self.selection
        self._replace_via_keyboard("\n", start, end)

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or end of next line if already there."""
        row, col = self.cursor_location
        line_end = len(self.document.get_line(row))
        if col >= line_end and row < self.document.line_count - 1:
            next_end = len(self.document.get_line(row + 1))
            self.move_cursor((row + 1, next_end), select=select)
        else:
            self.move_cursor((row, line_end), select=select)

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Move to start of line, or start of previous line if already there."""
        row, col = self.cursor_location
        if col == 0 and row > 0:
            self.move_cursor((row - 1, 0), select=select)
        else:
            self.move_cursor((row, 0), select=select)

    def action_open_editor(self) -> None:
        """Request to open external editor."""
        PromptInputBar = _prompt_bar_class()
        bar = self._find_prompt_bar()
        if bar:
            self._clear_soft_completion(cancel_timer=True)
            self._clear_xprompt_arg_hint()
            row, col = self.cursor_location
            bar.post_message(PromptInputBar.EditorRequested(self.text, row, col))

    def action_open_workflow_editor(self) -> None:
        """Request to open workflow YAML editor."""
        bar = self._find_prompt_bar()
        if bar and bar._mode == "feedback":
            return
        PromptInputBar = _prompt_bar_class()
        if bar:
            self._clear_soft_completion(cancel_timer=True)
            self._clear_xprompt_arg_hint()
            bar.post_message(PromptInputBar.WorkflowEditorRequested())

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        self._vim_mode = "normal"
        self._clear_soft_completion(cancel_timer=True)
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._snippet_tabstops = []
        self.read_only = True
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = f"{bar._base_title} [NORMAL]"
            bar.set_prompt_mode_subtitle("[Esc] clear  [i] insert  [^C] cancel")

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self.read_only = False
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar.border_title = bar._base_title
            bar.set_prompt_mode_subtitle("[Enter] send  [Esc] normal  [^C] cancel")

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            if self._file_completion_active:
                self._accept_file_completion()
            else:
                self._clear_xprompt_arg_hint()
                self.action_submit_prompt()
            return

        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            self._clear_file_completion()
            self._clear_soft_completion(cancel_timer=True)
            self._clear_xprompt_arg_hint()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape enters NORMAL mode
        if event.key == "escape":
            if self._file_completion_active:
                event.stop()
                event.prevent_default()
                self._clear_file_completion()
                self._clear_soft_completion(cancel_timer=True)
                self._clear_xprompt_arg_hint()
                return
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        if self._active_xprompt_arg_hint is not None and event.character in (":", "("):
            if self._can_apply_xprompt_arg_action():
                event.stop()
                event.prevent_default()
                if event.character == ":":
                    self._apply_xprompt_colon_arg_hint()
                else:
                    self._apply_xprompt_named_arg_hint()
                return
            self._clear_xprompt_arg_hint()

        # Active file completion navigation / acceptance.
        if self._file_completion_active:
            if event.key in ("ctrl+n", "down"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(1)
                return
            if event.key in ("ctrl+p", "up"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(-1)
                return
            if event.key == "ctrl+l":
                event.stop()
                event.prevent_default()
                self._accept_file_completion()
                return
            if event.key == "ctrl+d" and self._completion_kind == "file_history":
                event.stop()
                event.prevent_default()
                self._delete_selected_file_completion()
                return

        if event.key == "ctrl+l" and self._accept_soft_completion():
            event.stop()
            event.prevent_default()
            return

        # VCS MRU cycling: ctrl+n/ctrl+p when prompt is empty or VCS-only
        if not self._file_completion_active and event.key in ("ctrl+n", "ctrl+p"):
            from sase.xprompt._parsing import extract_vcs_workflow_tag

            text = self.text
            stripped = text.strip()
            is_vcs_only = not stripped
            current_prefix: str | None = None

            if stripped:
                # Append space for pattern matching (VCS pattern requires trailing \s)
                tag = extract_vcs_workflow_tag(stripped + " ")
                if tag is not None and stripped == tag.strip():
                    is_vcs_only = True
                    current_prefix = stripped

            if is_vcs_only:
                from sase.history.vcs_xprompt_mru import (
                    load_launchable_vcs_xprompt_mru,
                )

                mru = load_launchable_vcs_xprompt_mru()
                if mru:
                    direction = -1 if event.key == "ctrl+n" else 1
                    if self._vcs_mru_index is not None:
                        new_index = (self._vcs_mru_index + direction) % len(mru)
                    elif current_prefix is not None and current_prefix in mru:
                        base = mru.index(current_prefix)
                        new_index = (base + direction) % len(mru)
                    else:
                        new_index = 0 if direction == 1 else len(mru) - 1

                    self._vcs_mru_index = new_index
                    new_text = mru[new_index] + " "
                    self.text = new_text
                    self.move_cursor((0, len(new_text)))
                    event.stop()
                    event.prevent_default()
                    return

        # Ctrl+T in INSERT mode: trigger file path completion
        if event.key == "ctrl+t":
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            self._try_file_completion_tab()
            return

        # Tab in INSERT mode: expand snippet or advance tabstop (never insert literal tab)
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            if self._try_expand_snippet():
                return
            self._try_advance_tabstop()
            return

        # Detect '#@' trigger before the '@' is inserted (skip in feedback mode)
        if event.character == "@":
            bar = self._find_prompt_bar()
            if bar and bar._mode != "feedback":
                row, col = self.cursor_location
                if col > 0:
                    line = self.document.get_line(row)
                    if line[col - 1] == "#":
                        PromptInputBar = _prompt_bar_class()
                        bar.post_message(PromptInputBar.SnippetRequested())
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # Reset VCS MRU cycling on any non-cycling keypress
        if self._vcs_mru_index is not None:
            self._vcs_mru_index = None

        self._refresh_file_completion_from_cursor()
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()

    def _on_resize(self) -> None:
        """Scroll cursor into view after the parent resizes."""
        super()._on_resize()
        self.call_after_refresh(self.scroll_cursor_visible)
        bar = self._find_prompt_bar()
        if bar:
            bar._schedule_height_update()

    def on_blur(self) -> None:
        """Schedule a deferred refocus when the text area loses focus."""
        self.call_later(self._refocus_if_needed)

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

    def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Render the active xprompt argument hint through the prompt bar."""
        bar = self._find_prompt_bar()
        if bar:
            bar.show_xprompt_arg_hint(hint)

    def _clear_xprompt_arg_hint(self) -> None:
        """Clear active xprompt argument hint state and hide its panel."""
        if self._active_xprompt_arg_hint is None:
            return
        self._active_xprompt_arg_hint = None
        bar = self._find_prompt_bar()
        if bar and not self._file_completion_active:
            bar.hide_file_completions()

    def _active_xprompt_hint_is_current(self) -> bool:
        hint = self._active_xprompt_arg_hint
        if hint is None:
            return False
        return (
            self.text[hint.reference_start : hint.reference_end] == hint.reference_text
        )

    def _refresh_xprompt_arg_hint_from_cursor(self) -> None:
        """Refresh typed xprompt arg hints and dismiss stale accepted hints."""
        if self._file_completion_active or self._snippet_tabstops:
            return

        detected = self._detect_xprompt_arg_hint_from_cursor()
        if detected is not None:
            if detected != self._active_xprompt_arg_hint:
                self._active_xprompt_arg_hint = detected
                self._show_xprompt_arg_hint(detected)
            return

        hint = self._active_xprompt_arg_hint
        if hint is None:
            return
        if not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return
        cursor_offset = self._absolute_offset(self.cursor_location)
        if cursor_offset != hint.reference_end:
            self._clear_xprompt_arg_hint()

    def _detect_xprompt_arg_hint_from_cursor(self) -> ActiveXPromptArgHint | None:
        """Return a typed xprompt argument hint at the current cursor."""
        if "#" not in self.text:
            return None
        cursor_offset = self._absolute_offset(self.cursor_location)
        prefix = self.text[:cursor_offset]
        marker = prefix.rfind("#")
        if marker == -1 or not any(ch in prefix[marker:] for ch in (":", "(")):
            return None
        return detect_xprompt_arg_hint_at_cursor(
            self.text,
            cursor_offset,
            self._get_xprompt_arg_assist_entries(),
        )

    def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]:
        """Return cached xprompt assist entries for the prompt's project context."""
        project = self._xprompt_arg_assist_project_from_text()
        entries = self._xprompt_arg_assist_entries_by_project.get(project)
        if entries is None:
            entries = build_xprompt_assist_entries(project=project)
            self._xprompt_arg_assist_entries_by_project[project] = entries
        return entries

    def _get_warm_xprompt_arg_assist_entries(
        self,
    ) -> list[XPromptAssistEntry] | None:
        """Return warm xprompt entries for the current project, if available."""
        project = self._xprompt_arg_assist_project_from_text()
        return self._xprompt_arg_assist_entries_by_project.get(project)

    def _warm_current_xprompt_assist_entries(self) -> None:
        """Warm prompt-local xprompt entries for the current project in a worker."""
        self._schedule_xprompt_assist_warm(self._xprompt_arg_assist_project_from_text())

    def _schedule_xprompt_assist_warm(self, project: str | None) -> None:
        """Schedule a background xprompt assist catalog build if supported."""
        if project in self._xprompt_arg_assist_entries_by_project:
            return
        if project in self._xprompt_arg_assist_warming_projects:
            return
        if not callable(getattr(self.app, "get_prompt_completion_settings", None)):
            return

        self._xprompt_arg_assist_warming_projects.add(project)
        worker_name = f"prompt-xprompt-assist:{project or '<default>'}"
        self._xprompt_arg_assist_worker_projects[worker_name] = project

        def build() -> tuple[str | None, list[XPromptAssistEntry]]:
            return project, build_xprompt_assist_entries(project=project)

        self.run_worker(
            build,
            name=worker_name,
            thread=True,
        )

    def on_worker_state_changed(self, event: Any) -> None:
        """Apply async xprompt assist warm results."""
        worker = event.worker
        worker_name = str(getattr(worker, "name", ""))
        if not worker_name.startswith("prompt-xprompt-assist:"):
            return
        pending_project = self._xprompt_arg_assist_worker_projects.pop(
            worker_name,
            None,
        )
        if event.state != WorkerState.SUCCESS:
            self._xprompt_arg_assist_warming_projects.discard(pending_project)
            return
        project, entries = worker.result
        self._xprompt_arg_assist_entries_by_project[project] = entries
        self._xprompt_arg_assist_warming_projects.discard(project)
        if project == self._xprompt_arg_assist_project_from_text():
            self._on_prompt_completion_context_changed()

    def _prompt_completion_settings(self) -> PromptCompletionSettings:
        """Return prompt completion settings with a default for minimal apps."""
        getter = getattr(self.app, "get_prompt_completion_settings", None)
        if callable(getter):
            value = getter()
            if isinstance(value, PromptCompletionSettings):
                return value
        return DEFAULT_PROMPT_COMPLETION_SETTINGS

    def _on_prompt_completion_context_changed(self) -> None:
        """Debounce live prompt completion after text or cursor changes."""
        self._prompt_completion_generation += 1
        self._clear_stale_soft_completion()
        self._schedule_prompt_completion_refresh()

    def _schedule_prompt_completion_refresh(self) -> None:
        settings = self._prompt_completion_settings()
        if settings.auto != "soft" or self._soft_completion_blocked():
            self._clear_soft_completion(cancel_timer=True)
            return

        if self._prompt_completion_timer is not None:
            self._prompt_completion_timer.stop()
        generation = self._prompt_completion_generation
        text = self.text
        cursor_offset = self._absolute_offset(self.cursor_location)
        self._prompt_completion_timer = self.set_timer(
            settings.debounce_ms / 1000,
            lambda: self._fire_prompt_completion_timer(
                generation,
                text,
                cursor_offset,
            ),
        )

    def _fire_prompt_completion_timer(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        self._prompt_completion_timer = None
        if generation != self._prompt_completion_generation:
            return
        if text != self.text or cursor_offset != self._absolute_offset(
            self.cursor_location
        ):
            return
        if self._soft_completion_blocked():
            self._clear_soft_completion()
            return

        project = self._xprompt_arg_assist_project_from_text()
        entries = self._xprompt_arg_assist_entries_by_project.get(project)
        if entries is None and self._soft_completion_may_need_xprompt_entries(
            text, cursor_offset
        ):
            self._schedule_xprompt_assist_warm(project)

        suggestion = build_prompt_soft_completion(
            text=text,
            cursor_offset=cursor_offset,
            settings=self._prompt_completion_settings(),
            xprompt_entries=entries,
        )
        if generation != self._prompt_completion_generation:
            return
        self._set_soft_completion(suggestion)

    def _soft_completion_blocked(self) -> bool:
        if self._vim_mode != "insert":
            return True
        if self._file_completion_active or self._snippet_tabstops:
            return True
        bar = self._find_prompt_bar()
        return bool(bar and bar._mode == "feedback")

    def _soft_completion_may_need_xprompt_entries(
        self,
        text: str,
        cursor_offset: int,
    ) -> bool:
        if "#" in text:
            return True
        line_start = text.rfind("\n", 0, cursor_offset) + 1
        line_end = text.find("\n", cursor_offset)
        if line_end == -1:
            line_end = len(text)
        token_ctx = extract_token_around_cursor(
            text[line_start:line_end],
            cursor_offset - line_start,
        )
        return token_ctx is not None and is_xprompt_like_token(token_ctx[2])

    def _set_soft_completion(self, suggestion: PromptSoftCompletion | None) -> None:
        self._soft_completion = suggestion
        bar = self._find_prompt_bar()
        if bar is None:
            return
        if suggestion is None:
            bar.hide_soft_completion()
        else:
            bar.show_soft_completion(suggestion)

    def _clear_stale_soft_completion(self) -> None:
        if self._soft_completion is not None and not self._soft_completion_is_current():
            self._clear_soft_completion()

    def _clear_soft_completion(self, *, cancel_timer: bool = False) -> None:
        if cancel_timer and self._prompt_completion_timer is not None:
            self._prompt_completion_timer.stop()
            self._prompt_completion_timer = None
        if self._soft_completion is None:
            return
        self._soft_completion = None
        bar = self._find_prompt_bar()
        if bar:
            bar.hide_soft_completion()

    def _soft_completion_is_current(self) -> bool:
        suggestion = self._soft_completion
        if suggestion is None or self._soft_completion_blocked():
            return False
        cursor_offset = self._absolute_offset(self.cursor_location)
        return (
            cursor_offset == suggestion.replacement_end
            and 0 <= suggestion.replacement_start <= suggestion.replacement_end
            and suggestion.replacement_end <= len(self.text)
            and self.text[suggestion.replacement_start : suggestion.replacement_end]
            == suggestion.replacement_token
        )

    def _accept_soft_completion(self) -> bool:
        suggestion = self._soft_completion
        if suggestion is None:
            return False
        if not self._soft_completion_is_current():
            self._clear_soft_completion(cancel_timer=True)
            return False

        selected = suggestion.candidate
        accepted_kind = suggestion.completion_kind
        start = self._location_from_absolute(suggestion.replacement_start)
        end = self._location_from_absolute(suggestion.replacement_end)
        used_xprompt_skeleton = False
        if (
            accepted_kind == "xprompt"
            and isinstance(selected.metadata, XPromptAssistEntry)
            and selected.insertion.startswith("#")
        ):
            used_xprompt_skeleton = self._expand_snippet_template_at_range(
                xprompt_completion_skeleton(selected.metadata),
                start,
                end,
            )

        if not used_xprompt_skeleton:
            self._replace_absolute_range(
                suggestion.replacement_start,
                suggestion.replacement_end,
                selected.insertion,
            )

        self._clear_soft_completion(cancel_timer=True)
        if accepted_kind == "xprompt":
            if used_xprompt_skeleton:
                self._refresh_xprompt_completion_skeleton_hint(selected)
            else:
                self._clear_xprompt_arg_hint()
        elif accepted_kind.startswith("xprompt_arg_"):
            self._refresh_xprompt_arg_hint_from_cursor()
        else:
            self._clear_xprompt_arg_hint()
        return True

    def _xprompt_arg_assist_project_from_text(self) -> str | None:
        """Derive project-local xprompt context from a leading VCS tag."""
        tag = extract_vcs_workflow_tag(self.text)
        if tag is None:
            return None
        return extract_project_from_vcs_tag(tag)

    def _maybe_show_inserted_xprompt_arg_hint(
        self,
        reference_start: int,
        reference_end: int,
    ) -> bool:
        """Show a post-accept hint after non-completion xprompt insertion."""
        hint = accepted_xprompt_arg_hint(
            self.text,
            reference_start,
            reference_end,
            self._get_xprompt_arg_assist_entries(),
        )
        if hint is None:
            self._clear_xprompt_arg_hint()
            return False
        self._active_xprompt_arg_hint = hint
        self._show_xprompt_arg_hint(hint)
        return True

    def _can_apply_xprompt_arg_action(self) -> bool:
        """Return True when an active hint can consume syntax action keys."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            return False
        return self._absolute_offset(self.cursor_location) == hint.reference_end

    def _apply_xprompt_colon_arg_hint(self) -> bool:
        """Rewrite the accepted reference with colon-argument syntax."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        replacement = f"{hint.entry.insertion}:"
        self._replace_via_keyboard(replacement, start, end)
        new_end = hint.reference_start + len(replacement)
        self.cursor_location = self._location_from_absolute(new_end)
        next_hint = ActiveXPromptArgHint(
            entry=hint.entry,
            reference_start=hint.reference_start,
            reference_end=new_end,
            reference_text=replacement,
            trigger_mode="colon",
            active_input_index=hint.active_input_index,
        )
        self._active_xprompt_arg_hint = next_hint
        self._show_xprompt_arg_hint(next_hint)
        return True

    def _apply_xprompt_named_arg_hint(self) -> bool:
        """Rewrite the accepted reference with a named-argument snippet."""
        hint = self._active_xprompt_arg_hint
        if hint is None or not self._active_xprompt_hint_is_current():
            self._clear_xprompt_arg_hint()
            return False
        if self._absolute_offset(self.cursor_location) != hint.reference_end:
            self._clear_xprompt_arg_hint()
            return False

        start = self._location_from_absolute(hint.reference_start)
        end = self._location_from_absolute(hint.reference_end)
        self._clear_xprompt_arg_hint()
        return self._expand_snippet_template_at_range(
            named_args_skeleton(hint.entry),
            start,
            end,
        )

    def _refocus_if_needed(self) -> None:
        """Refocus this text area unless a modal is active."""
        if self.is_mounted and not isinstance(self.app.screen, ModalScreen):
            self.focus()
