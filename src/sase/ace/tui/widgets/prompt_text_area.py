"""Custom TextArea with multiline support and vim/readline keybindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import TextArea

from sase.ace.tui.widgets._file_completion import FileCompletionMixin
from sase.ace.tui.widgets._jinja_diagnostics import JinjaDiagnosticsMixin
from sase.ace.tui.widgets._jinja_highlight import JinjaHighlightMixin
from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._prompt_soft_completion import PromptSoftCompletionMixin
from sase.ace.tui.widgets._snippets import SnippetExpansionMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets._vim_registers import VimRegister
from sase.ace.tui.widgets._vcs_mru_cycling import (
    VcsMruCycleKey,
    VcsMruCyclingMixin,
)
from sase.ace.tui.widgets._xprompt_arg_hints import XPromptArgHintMixin
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
)
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    build_xprompt_assist_entries,
)
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


__all__ = [
    "PromptTextArea",
    "build_xprompt_assist_entries",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
]


class PromptTextArea(
    JinjaDiagnosticsMixin,
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
        ("ctrl+shift+g", "open_all_editor", "Edit all in editor"),
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
        self._last_mutation_keys: list[str] = []
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
        """Submit the prompt text (only the selected pane in a stack)."""
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_text_submission(self.text)

    def action_submit_prompt_stack(self) -> None:
        """Submit the whole prompt stack as one multi-prompt (``<ctrl+s>``)."""
        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        bar = self._find_prompt_bar()
        if bar:
            bar._handle_whole_stack_submission()

    def action_open_prompt_history(self) -> None:
        """Request prompt history, filtered by the current single-line prompt."""
        bar = self._find_prompt_bar()
        if not bar or bar._mode != "prompt":
            return
        if self.document.line_count != 1:
            return

        self._snippet_tabstops = []
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None

        PromptInputBar = _prompt_bar_class()
        bar.post_message(
            PromptInputBar.HistoryRequested(
                initial_filter=self.text,
                preserve_prompt_bar=True,
            )
        )

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

    def action_open_all_editor(self) -> None:
        """Request to open the whole prompt stack in the external editor.

        Distinct from ``^G`` (active-pane only): this is a prompt-mode,
        multi-agent surface keymap, so feedback / approve-prompt bars ignore it.
        Keypress handling is kept light — clear transient completion / arg-hint
        state and post the message — while the bar owns serializing the stack to
        xprompt markdown off the keypress path.
        """
        bar = self._find_prompt_bar()
        if not bar or bar._mode != "prompt":
            return
        PromptInputBar = _prompt_bar_class()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()
        bar.post_message(PromptInputBar.AllEditorRequested())

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

    def _open_recursive_file_finder(self) -> None:
        """Open the recursive fuzzy file finder modal (Ctrl+R).

        Captures the recursive root and prompt token-range, enumerates
        candidates once, and pushes the finder modal.  On accept, the selected
        path replaces the captured token range in the prompt.
        """
        from sase.ace.tui.modals.recursive_finder_modal import (
            RecursiveFileFinderModal,
        )
        from sase.ace.tui.widgets.recursive_file_finder import (
            enumerate_recursive_candidates,
        )

        ctx = self._compute_recursive_finder_context()
        if ctx is None:
            return

        candidates, truncated = enumerate_recursive_candidates(
            ctx.root_abs, ctx.root_display
        )
        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)

        def _on_result(result: CompletionCandidate | None) -> None:
            self._refocus_if_needed()
            if result is not None:
                self._insert_finder_result(ctx, result)

        self.app.push_screen(
            RecursiveFileFinderModal(
                root_label=ctx.root_display or "./",
                candidates=candidates,
                truncated=truncated,
                initial_query=ctx.query,
            ),
            _on_result,
        )

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._clear_visual_state()
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._vcs_mru_index = None
        self._vim_mode = "normal"
        self._clear_soft_completion(cancel_timer=True)
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self._snippet_tabstops = []
        self.read_only = True
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        bar = self._find_prompt_bar()
        if bar:
            bar._refresh_title("[NORMAL]")
            bar.set_prompt_mode_subtitle(bar.normal_mode_subtitle())

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._clear_visual_state()
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self.read_only = False
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        bar = self._find_prompt_bar()
        if bar:
            bar._refresh_title()
            bar.set_prompt_mode_subtitle(bar.insert_mode_subtitle())

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

        # Whole-stack submit. ``^S`` joins the stack into one multi-prompt.
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.action_submit_prompt_stack()
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

        if event.key == "ctrl+k":
            event.stop()
            event.prevent_default()
            self.action_open_prompt_history()
            return

        # Prompt-stack pane focus navigation, available while typing (insert)
        # or browsing (normal).  Only the shift chord matches: ``ctrl+j`` stays
        # newline and ``ctrl+k`` stays prompt history.  The event is always
        # swallowed so it never falls through to text insertion or global
        # bindings, even when no movement is possible (single pane / at edge).
        if event.key in ("ctrl+shift+j", "ctrl+shift+k") and self._vim_mode in {
            "insert",
            "normal",
        }:
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar is not None:
                delta = 1 if event.key == "ctrl+shift+j" else -1
                bar.focus_relative(delta, target_mode=self._vim_mode)
            return

        # Prompt-stack pane reorder, the chord pair adjacent to pane focus.
        # ``ctrl+shift+h`` moves the active pane higher/earlier, ``ctrl+shift+l``
        # lower/later, mirroring the vertical stack layout.  Only the shift chord
        # matches, so ``ctrl+l`` stays soft-completion accept and ``ctrl+h`` is
        # untouched.  The event is always swallowed in insert / normal mode so it
        # never falls through to text insertion, completion acceptance, or global
        # bindings, even when no movement is possible (single pane / at edge).
        if event.key in ("ctrl+shift+h", "ctrl+shift+l") and self._vim_mode in {
            "insert",
            "normal",
        }:
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar is not None:
                delta = -1 if event.key == "ctrl+shift+h" else 1
                bar.move_active_pane(delta, target_mode=self._vim_mode)
            return

        # Prompt-stack add-pane.  ``Ctrl+-`` (Textual normalizes ``-`` to
        # ``minus``) appends a new empty bottom pane and drops into it, the
        # structural sibling of the Ctrl+Shift focus / reorder chords.  Like
        # them it works while typing (insert) or browsing (normal), and the
        # event is always swallowed so the chord never falls through to text
        # insertion, completion, normal-mode editing, or app-level bindings.
        # ``add_bottom_pane`` no-ops outside prompt mode, so feedback /
        # approve-prompt bars stay non-stackable.
        if event.key == "ctrl+minus" and self._vim_mode in {"insert", "normal"}:
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar is not None:
                bar.add_bottom_pane()
            return

        if self._vim_mode in {"visual", "visual_line"}:
            if self._handle_visual_mode_key(event):
                event.stop()
                event.prevent_default()
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

        # Ctrl+R: open the recursive fuzzy file finder. Works whether or not
        # the Ctrl+T completion panel is open — when it is, Case A derives the
        # recursive root from the currently-selected entry.
        if event.key == "ctrl+r":
            event.stop()
            event.prevent_default()
            self._open_recursive_file_finder()
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

        if event.key == "ctrl+l" and self._accept_or_build_soft_completion():
            event.stop()
            event.prevent_default()
            return

        if event.key in ("ctrl+n", "ctrl+p") and self._handle_vcs_mru_cycle_key(
            cast(VcsMruCycleKey, event.key)
        ):
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

        if self._try_jinja_auto_pair(event):
            event.stop()
            event.prevent_default()
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

    def _try_jinja_auto_pair(self, event: Key) -> bool:
        """Auto-pair Jinja delimiters after the second opener character."""
        if event.character not in ("{", "%", "#"):
            return False
        start, end = self.selection
        if start != end:
            return False
        row, col = self.cursor_location
        if col <= 0:
            return False
        line = self.document.get_line(row)
        if line[col - 1] != "{":
            return False
        if col < len(line) and not line[col].isspace():
            return False

        pairs = {
            "{": ("{  }}", 2),
            "%": ("%  %}", 2),
            "#": ("#  #}", 2),
        }
        insert, cursor_delta = pairs[event.character]
        self._replace_via_keyboard(insert, (row, col), (row, col))
        self.cursor_location = (row, col + cursor_delta)
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
        return True

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

    def _refocus_if_needed(self) -> None:
        """Refocus this text area unless a modal is active or a sibling pane owns it.

        With a multi-pane prompt stack, focus intentionally moves between panes;
        the just-blurred pane must not steal focus back.  Only the bar's active
        pane refocuses itself (the single-pane bar always treats itself as
        active), preserving the original "keep the prompt focused" behavior.
        """
        if not self.is_mounted or isinstance(self.app.screen, ModalScreen):
            return
        bar = self._find_prompt_bar()
        if bar is not None:
            # Focus intentionally moved to the frontmatter panel (or its inline /
            # raw editors); let it keep focus instead of snapping back here.
            owns = getattr(bar, "_frontmatter_panel_owns_focus", None)
            if callable(owns) and owns():
                return
            try:
                if bar.active_text_area() is not self:
                    return
            except Exception:
                pass
        self.focus()
