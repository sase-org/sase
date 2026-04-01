"""File path completion mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.file_completion import (
    MAX_VISIBLE,
    CompletionCandidate,
    build_completion_candidates,
    extract_token_around_cursor,
    is_path_like_token,
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
            token, rows, self._file_completion_index, scroll_offset
        )

    def _clear_file_completion(self) -> None:
        """Reset path completion state and hide panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._update_file_completion_panel("")

    def _move_file_completion(self, delta: int) -> bool:
        """Move highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        size = len(self._file_completion_candidates)
        self._file_completion_index = (self._file_completion_index + delta) % size
        ctx = self._get_path_token_context()
        self._update_file_completion_panel("" if ctx is None else ctx[3])
        return True

    def _accept_file_completion(self) -> bool:
        """Accept currently highlighted completion candidate."""
        if not self._file_completion_active or not self._file_completion_candidates:
            return False
        ctx = self._get_path_token_context()
        if ctx is None:
            self._clear_file_completion()
            return False
        row, start, end, _token = ctx
        selected = self._file_completion_candidates[self._file_completion_index]
        self._replace_token_text(row, start, end, selected.insertion)
        # Directory drill-down: open completion for the accepted directory
        if selected.is_dir:
            self._file_completion_active = False
            self._file_completion_candidates = []
            self._file_completion_index = 0
            if not self._try_file_completion_tab():
                self._clear_file_completion()
        else:
            self._clear_file_completion()
        return True

    def _refresh_file_completion_from_cursor(self) -> None:
        """Recompute active completions after edits or cursor movement."""
        if not self._file_completion_active:
            return

        ctx = self._get_path_token_context()
        if ctx is None:
            self._clear_file_completion()
            return

        _row, _start, _end, token = ctx
        previous = None
        if self._file_completion_candidates:
            previous = self._file_completion_candidates[
                self._file_completion_index
            ].insertion
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
        """Handle Tab-driven file completion for path tokens."""
        ctx = self._get_path_token_context()
        if ctx is None:
            self._clear_file_completion()
            return False

        row, start, end, token = ctx
        candidates, shared_extension = build_completion_candidates(token)
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
            ctx = self._get_path_token_context()
            if ctx is None:
                self._clear_file_completion()
                return True
            row, start, end, token = ctx
            candidates, _ = build_completion_candidates(token)
            if not candidates:
                self._clear_file_completion()
                return True

        self._file_completion_active = True
        self._file_completion_candidates = candidates
        self._file_completion_index = 0
        self._update_file_completion_panel(token)
        return True
