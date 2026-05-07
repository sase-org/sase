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
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    XPromptArgCompletionContext,
    detect_xprompt_arg_completion_at_cursor,
    required_inputs,
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
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None

        def _find_prompt_bar(self) -> Any: ...

        def _replace_via_keyboard(
            self, insert: str, start: tuple[int, int], end: tuple[int, int]
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...

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

    def _replace_absolute_range(
        self,
        start_offset: int,
        end_offset: int,
        replacement: str,
    ) -> None:
        """Replace an absolute prompt range and put cursor at replacement end."""
        start = self._location_from_absolute(start_offset)
        end = self._location_from_absolute(end_offset)
        self._replace_via_keyboard(replacement, start, end)
        self.cursor_location = self._location_from_absolute(
            start_offset + len(replacement)
        )

    def _update_file_completion_panel(self, token: str) -> None:
        """Sync completion UI with the current completion state."""
        bar = self._find_prompt_bar()
        if bar is None:
            return

        if not self._file_completion_active or not self._file_completion_candidates:
            bar.hide_file_completions()
            return

        rows = self._file_completion_candidates
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

    def _clear_file_completion(self, *, clear_xprompt_arg_hint: bool = True) -> None:
        """Reset path completion state and hide panel."""
        self._file_completion_active = False
        self._file_completion_candidates = []
        self._file_completion_index = 0
        self._completion_kind = "file"
        self._update_file_completion_panel("")
        if clear_xprompt_arg_hint:
            self._clear_xprompt_arg_hint()

    def _maybe_show_accepted_xprompt_arg_hint(
        self,
        selected: CompletionCandidate,
        row: int,
        start: int,
    ) -> bool:
        """Show post-accept argument hints for required-input xprompts."""
        if not isinstance(selected.metadata, XPromptAssistEntry):
            self._clear_xprompt_arg_hint()
            return False
        if not selected.insertion.startswith("#"):
            self._clear_xprompt_arg_hint()
            return False
        if not required_inputs(selected.metadata):
            self._clear_xprompt_arg_hint()
            return False

        reference_start = self._absolute_offset((row, start))
        reference_end = reference_start + len(selected.insertion)
        hint = ActiveXPromptArgHint(
            entry=selected.metadata,
            reference_start=reference_start,
            reference_end=reference_end,
            reference_text=selected.insertion,
        )
        self._active_xprompt_arg_hint = hint
        self._show_xprompt_arg_hint(hint)
        return True

    def _get_token_context(self) -> tuple[int, int, int, str] | None:
        """Return token context using the appropriate getter for the active kind."""
        if self._completion_kind == "xprompt":
            return self._get_xprompt_token_context()
        if self._completion_kind.startswith("xprompt_arg_"):
            return self._get_xprompt_arg_token_context()
        return self._get_path_token_context()

    def _get_xprompt_arg_completion_context(
        self,
    ) -> XPromptArgCompletionContext | None:
        """Return an xprompt argument completion context at the current cursor."""
        if "#" not in self.text:
            return None
        cursor_offset = self._absolute_offset(self.cursor_location)
        return detect_xprompt_arg_completion_at_cursor(
            self.text,
            cursor_offset,
            self._get_xprompt_arg_assist_entries(),
        )

    def _get_xprompt_arg_token_context(self) -> tuple[int, int, int, str] | None:
        """Return row-local token context for active xprompt argument completion."""
        ctx = self._get_xprompt_arg_completion_context()
        if ctx is None:
            return None
        row, start = self._location_from_absolute(ctx.value_start)
        end_row, end = self._location_from_absolute(ctx.value_end)
        if row != end_row:
            return None
        return row, start, end, _effective_xprompt_arg_token(ctx)

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
        accepted_kind = self._completion_kind
        self._replace_token_text(row, start, end, selected.insertion)
        # Directory drill-down: open completion for the accepted directory.
        if selected.is_dir and self._completion_kind in ("file", "xprompt_arg_path"):
            self._file_completion_active = False
            self._file_completion_candidates = []
            self._file_completion_index = 0
            if not self._try_file_completion_tab():
                self._clear_file_completion()
        else:
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            if accepted_kind == "xprompt":
                self._maybe_show_accepted_xprompt_arg_hint(selected, row, start)
            elif accepted_kind.startswith("xprompt_arg_"):
                self._refresh_xprompt_arg_hint_from_cursor()
            else:
                self._clear_xprompt_arg_hint()
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
        # at the cursor dismisses. Cursor movement within whitespace is fine.
        if self._completion_kind == "file_history":
            if self._extract_token_around_cursor() is not None:
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
        elif self._completion_kind.startswith("xprompt_arg_"):
            arg_ctx = self._get_xprompt_arg_completion_context()
            if arg_ctx is None:
                self._clear_file_completion()
                return
            candidates, _shared = _build_xprompt_arg_completion_candidates(arg_ctx)
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
        arg_ctx = self._get_xprompt_arg_completion_context()
        if arg_ctx is not None:
            return self._try_xprompt_arg_completion_tab(arg_ctx)

        self._clear_xprompt_arg_hint()
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            return self._try_file_history_completion()

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
            selected = candidates[0]
            accepted_kind = self._completion_kind
            self._replace_token_text(row, start, end, selected.insertion)
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            if accepted_kind == "xprompt":
                self._maybe_show_accepted_xprompt_arg_hint(selected, row, start)
            elif accepted_kind.startswith("xprompt_arg_"):
                self._refresh_xprompt_arg_hint_from_cursor()
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
            elif self._completion_kind.startswith("xprompt_arg_"):
                arg_ctx = self._get_xprompt_arg_completion_context()
                if arg_ctx is None:
                    self._clear_file_completion()
                    return True
                candidates, _ = _build_xprompt_arg_completion_candidates(arg_ctx)
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

    def _try_xprompt_arg_completion_tab(
        self,
        ctx: XPromptArgCompletionContext,
    ) -> bool:
        """Handle Ctrl+T-driven completion inside xprompt argument syntax."""
        candidates, shared_extension = _build_xprompt_arg_completion_candidates(ctx)
        self._completion_kind = ctx.completion_kind

        if not candidates:
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        if len(candidates) == 1:
            selected = candidates[0]
            self._replace_absolute_range(
                ctx.value_start, ctx.value_end, selected.insertion
            )
            self._clear_file_completion(clear_xprompt_arg_hint=False)
            self._refresh_xprompt_arg_hint_from_cursor()
            return True

        token = _effective_xprompt_arg_token(ctx)
        if shared_extension:
            next_token = f"{token}{shared_extension}"
            self._replace_absolute_range(ctx.value_start, ctx.value_end, next_token)
            next_ctx = self._get_xprompt_arg_completion_context()
            if next_ctx is None:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
                return True
            candidates, _ = _build_xprompt_arg_completion_candidates(next_ctx)
            ctx = next_ctx
            token = _effective_xprompt_arg_token(ctx)
            self._completion_kind = ctx.completion_kind
            if not candidates:
                self._clear_file_completion(clear_xprompt_arg_hint=False)
                self._refresh_xprompt_arg_hint_from_cursor()
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


def _effective_xprompt_arg_token(ctx: XPromptArgCompletionContext) -> str:
    """Return the token passed to an underlying completion engine."""
    if ctx.completion_kind != "xprompt_arg_path":
        return ctx.token
    if not ctx.token:
        return "./"
    if is_path_like_token(ctx.token):
        return ctx.token
    return f"./{ctx.token}"


def _build_xprompt_arg_completion_candidates(
    ctx: XPromptArgCompletionContext,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for an xprompt argument completion context."""
    if ctx.completion_kind == "xprompt_arg_path":
        return build_completion_candidates(_effective_xprompt_arg_token(ctx))
    if ctx.completion_kind == "xprompt_arg_value":
        return _build_bool_completion_candidates(ctx.token)
    if ctx.completion_kind == "xprompt_arg_name":
        return _build_named_arg_completion_candidates(ctx)
    return [], ""


def _build_bool_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    partial = token.lower()
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value,
        )
        for value in ("true", "false")
        if value.startswith(partial)
    ]
    return candidates, ""


def _build_named_arg_completion_candidates(
    ctx: XPromptArgCompletionContext,
) -> tuple[list[CompletionCandidate], str]:
    partial = ctx.token.lower()
    candidates = [
        CompletionCandidate(
            display=f"{inp.name}=",
            insertion=f"{inp.name}=",
            is_dir=False,
            name=inp.name,
            metadata=inp,
        )
        for inp in ctx.entry.inputs
        if inp.name not in ctx.used_arg_names and inp.name.lower().startswith(partial)
    ]
    candidates.sort(key=lambda c: c.name.lower())
    return candidates, ""
