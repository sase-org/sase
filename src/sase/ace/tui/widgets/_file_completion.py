"""File path completion mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.file_completion import (
    MAX_VISIBLE,
    CompletionCandidate,
    build_completion_candidates,
    build_file_history_completion_candidates,
    extract_token_around_cursor,
    is_path_like_token,
)
from sase.ace.tui.widgets.xprompt_completion import (
    build_xprompt_completion_candidates,
    is_xprompt_like_token,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class FileCompletionMixin(_MixinBase):
    """Mixin providing file path completion for PromptTextArea.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    # -- Attributes and method stubs for type checking --
    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str

        def _find_prompt_bar(self) -> Any: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

    # -- Mixin implementation --

    def _extract_token_around_cursor(self) -> tuple[int, int, str] | None:
        """Extract token bounds around the cursor in the current line."""
        row, col = self.cursor_location
        line = self.document.get_line(row)
        return extract_token_around_cursor(line, col)

    def _cursor_at_empty_prefix(self) -> bool:
        """True when the current line is whitespace-only up to the cursor."""
        row, col = self.cursor_location
        line = self.document.get_line(row)
        return line[:col].strip() == ""

    def _get_path_token_context(self) -> tuple[int, int, int, str] | None:
        """Return (row, start, end, token) for the current path token."""
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            return None

        start, end, token = token_info
        if not is_path_like_token(token):
            return None
        row, _ = self.cursor_location
        return row, start, end, token

    def _get_xprompt_token_context(self) -> tuple[int, int, int, str] | None:
        """Return (row, start, end, token) for the current xprompt token."""
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            return None

        start, end, token = token_info
        if not is_xprompt_like_token(token):
            return None
        row, _ = self.cursor_location
        return row, start, end, token

    def _replace_token_text(self, row: int, start: int, end: int, token: str) -> None:
        """Replace token range and put cursor at token end."""
        self._replace_via_keyboard(token, (row, start), (row, end))
        self.cursor_location = (row, start + len(token))

    def _update_file_completion_panel(self, token: str) -> None:
        """Sync completion UI with the current completion state."""
        bar = self._find_prompt_bar()
        if bar is None:
            return

        if not self._file_completion_active or not self._file_completion_candidates:
            bar.hide_file_completions()
            return

        rows = [(c.display, c.is_dir) for c in self._file_completion_candidates]
        total = len(rows)
        if total <= MAX_VISIBLE:
            scroll_offset = 0
        else:
            half = MAX_VISIBLE // 2
            scroll_offset = max(
                0, min(self._file_completion_index - half, total - MAX_VISIBLE)
            )
        bar.show_file_completions(
            token,
            rows,
            self._file_completion_index,
            scroll_offset,
            completion_kind=self._completion_kind,
        )

    def _clear_file_completion(self) -> None:
        """Reset path completion state and hide panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._completion_kind = "file"
        self._update_file_completion_panel("")

    def _get_token_context(self) -> tuple[int, int, int, str] | None:
        """Return token context using the appropriate getter for the active kind."""
        if self._completion_kind == "xprompt":
            return self._get_xprompt_token_context()
        return self._get_path_token_context()

    def _move_file_completion(self, delta: int) -> bool:
        """Move highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        size = len(self._file_completion_candidates)
        self._file_completion_index = (self._file_completion_index + delta) % size
        ctx = self._get_token_context()
        self._update_file_completion_panel("" if ctx is None else ctx[3])
        return True

    def _accept_file_completion(self) -> bool:
        """Accept currently highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        selected = self._file_completion_candidates[self._file_completion_index]
        if self._completion_kind == "file_history":
            row, col = self.cursor_location
            self._replace_via_keyboard(selected.insertion, (row, col), (row, col))
            self.cursor_location = (row, col + len(selected.insertion))
            self._clear_file_completion()
            return True
        ctx = self._get_token_context()
        if ctx is None:
            self._clear_file_completion()
            return False
        row, start, end, _token = ctx
        self._replace_token_text(row, start, end, selected.insertion)
        # Directory drill-down: open completion for the accepted directory
        # (only applies to file completion, not xprompt)
        if selected.is_dir and self._completion_kind == "file":
            self._file_completion_active = False
            self._file_completion_candidates = []
            self._file_completion_index = 0
            if not self._try_file_completion_tab():
                self._clear_file_completion()
        else:
            self._clear_file_completion()
        return True

    def _delete_selected_file_completion(self) -> bool:
        """Delete the highlighted entry from file-history completion."""
        if not self._file_completion_active:
            return False
        if self._completion_kind != "file_history":
            return False
        if not self._file_completion_candidates:
            return False

        from sase.history.file_references import remove_file_reference

        idx = self._file_completion_index
        if idx >= len(self._file_completion_candidates):
            return False

        victim = self._file_completion_candidates[idx].insertion
        remove_file_reference(victim)

        del self._file_completion_candidates[idx]
        if not self._file_completion_candidates:
            self._clear_file_completion()
            return True

        self._file_completion_index = min(
            idx, len(self._file_completion_candidates) - 1
        )
        self._update_file_completion_panel("")
        return True

    def _refresh_file_completion_from_cursor(self) -> None:
        """Recompute active completions after edits or cursor movement."""
        if not self._file_completion_active:
            return

        # file_history mode has no active token — any edit that creates one
        # (or moves the cursor so the prefix is no longer empty) dismisses.
        if self._completion_kind == "file_history":
            if self._extract_token_around_cursor() is not None or not (
                self._cursor_at_empty_prefix()
            ):
                self._clear_file_completion()
            return

        ctx = self._get_token_context()
        if ctx is None:
            self._clear_file_completion()
            return

        _row, _start, _end, token = ctx
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion
        if self._completion_kind == "xprompt":
            candidates, _shared = build_xprompt_completion_candidates(token)
        else:
            candidates, _shared = build_completion_candidates(token)
        if not candidates:
            self._clear_file_completion()
            return

        self._file_completion_candidates = candidates
        if previous is not None:
            for i, candidate in enumerate(candidates):
                if candidate.insertion == previous:
                    self._file_completion_index = i
                    break
            else:
                self._file_completion_index = min(
                    self._file_completion_index, len(candidates) - 1
                )
        else:
            self._file_completion_index = min(
                self._file_completion_index, len(candidates) - 1
            )

        self._update_file_completion_panel(token)

    def _try_file_completion_tab(self) -> bool:
        """Handle Ctrl+T-driven completion for path, xprompt, or history."""
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            if self._cursor_at_empty_prefix():
                return self._try_file_history_completion()
            self._clear_file_completion()
            return False

        _start, _end, raw_token = token_info

        # Determine completion kind from the raw token.
        if is_xprompt_like_token(raw_token):
            self._completion_kind = "xprompt"
            ctx = self._get_xprompt_token_context()
            if ctx is None:
                self._clear_file_completion()
                return False
            row, start, end, token = ctx
            candidates, shared_extension = build_xprompt_completion_candidates(token)
        elif is_path_like_token(raw_token):
            self._completion_kind = "file"
            ctx = self._get_path_token_context()
            if ctx is None:
                self._clear_file_completion()
                return False
            row, start, end, token = ctx
            candidates, shared_extension = build_completion_candidates(token)
        else:
            self._clear_file_completion()
            return False

        if not candidates:
            self._clear_file_completion()
            return True

        if len(candidates) == 1:
            self._replace_token_text(row, start, end, candidates[0].insertion)
            self._clear_file_completion()
            return True

        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_token_text(row, start, end, next_token)
            ctx = self._get_token_context()
            if ctx is None:
                self._clear_file_completion()
                return True
            row, start, end, token = ctx
            if self._completion_kind == "xprompt":
                candidates, _ = build_xprompt_completion_candidates(token)
            else:
                candidates, _ = build_completion_candidates(token)
            if not candidates:
                self._clear_file_completion()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True

    def _try_file_history_completion(self) -> bool:
        """Show the file-reference history panel at an empty cursor prefix."""
        candidates, _shared = build_file_history_completion_candidates()
        if not candidates:
            self._clear_file_completion()
            return True

        self._completion_kind = "file_history"
        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel("")
        return True
