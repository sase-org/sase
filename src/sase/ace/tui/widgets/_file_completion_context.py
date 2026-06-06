"""Token and range context helpers for prompt file completion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_xprompt_args import (
    _cursor_prefix_may_contain_xprompt_args,
    effective_xprompt_arg_token,
)
from sase.ace.tui.widgets.directive_completion import (
    extract_directive_token_around_cursor,
)
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    extract_token_around_cursor,
    is_path_like_token,
)
from sase.ace.tui.widgets.prompt_completion_root import (
    resolve_prompt_completion_base_dir,
)
from sase.ace.tui.widgets.recursive_file_finder import (
    RecursiveFinderContext,
    derive_root_from_path,
    resolve_root_abs,
    split_root_and_query,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptArgCompletionContext,
    detect_xprompt_arg_completion_at_cursor,
)
from sase.ace.tui.widgets.xprompt_completion import (
    build_xprompt_completion_candidates,
    is_xprompt_like_token,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_RECURSIVE_PATH_KINDS: frozenset[str] = frozenset(
    {"file", "file_history", "xprompt_arg_path"}
)
"""Completion kinds whose active selection can seed the Ctrl+R recursive root."""


class FileCompletionContextMixin(_MixinBase):
    """Mixin providing token, path, and recursive finder context helpers."""

    if TYPE_CHECKING:
        _file_completion_candidates: list[CompletionCandidate]
        _file_completion_index: int
        _file_completion_active: bool
        _completion_kind: str

        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _get_xprompt_arg_assist_entries(self) -> list[XPromptAssistEntry]: ...
        def _get_warm_xprompt_arg_assist_entries(
            self,
        ) -> list[XPromptAssistEntry] | None: ...

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

    def _get_directive_token_context(self) -> tuple[int, int, int, str] | None:
        """Return (row, start, end, token) for the current directive token."""
        row, col = self.cursor_location
        line = self.document.get_line(row)
        token_info = extract_directive_token_around_cursor(line, col)
        if token_info is None:
            return None

        start, end, token = token_info
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

    def _prompt_completion_base_dir(self) -> str | None:
        """Return the prompt-selected filesystem base for path completion."""
        return resolve_prompt_completion_base_dir(self.text)

    def _compute_recursive_finder_context(self) -> RecursiveFinderContext | None:
        """Resolve the recursive root and prompt range to replace for Ctrl+R."""
        if (
            self._file_completion_active
            and self._completion_kind in _RECURSIVE_PATH_KINDS
            and self._file_completion_candidates
        ):
            ctx = self._recursive_context_from_active_completion()
            if ctx is not None:
                return ctx
        return self._recursive_context_from_cursor_token()

    def _recursive_context_from_active_completion(
        self,
    ) -> RecursiveFinderContext | None:
        """Build a Ctrl+R context rooted at the active Ctrl+T selection."""
        selected = self._file_completion_candidates[self._file_completion_index]
        root_display = derive_root_from_path(selected.insertion, selected.is_dir)
        root_abs = resolve_root_abs(
            root_display,
            base_dir=self._prompt_completion_base_dir(),
        )
        row, col = self.cursor_location
        token_info = self._extract_token_around_cursor()
        if token_info is not None:
            start, end, _token = token_info
        else:
            start = end = col
        return RecursiveFinderContext(root_display, root_abs, row, start, end, "")

    def _recursive_context_from_cursor_token(self) -> RecursiveFinderContext:
        """Build a Ctrl+R context from the path token around the cursor."""
        row, col = self.cursor_location
        base_dir = self._prompt_completion_base_dir()
        token_info = self._extract_token_around_cursor()
        if token_info is None:
            return RecursiveFinderContext(
                "",
                resolve_root_abs("", base_dir=base_dir),
                row,
                col,
                col,
                "",
            )
        start, end, token = token_info
        root_display, query = split_root_and_query(token)
        root_abs = resolve_root_abs(root_display, base_dir=base_dir)
        return RecursiveFinderContext(root_display, root_abs, row, start, end, query)

    def _insert_finder_result(
        self,
        ctx: RecursiveFinderContext,
        candidate: CompletionCandidate,
    ) -> None:
        """Insert a chosen recursive-finder path at the captured token range."""
        self._replace_token_text(ctx.row, ctx.start, ctx.end, candidate.insertion)

    def _get_token_context(self) -> tuple[int, int, int, str] | None:
        """Return token context using the appropriate getter for the active kind."""
        if self._completion_kind == "directive":
            return self._get_directive_token_context()
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
        if not _cursor_prefix_may_contain_xprompt_args(self.text, cursor_offset):
            return None
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
        return row, start, end, effective_xprompt_arg_token(ctx)

    def _build_xprompt_completion_candidates(
        self,
        token: str,
    ) -> tuple[list[CompletionCandidate], str]:
        """Build xprompt candidates, reusing warm prompt-local cache if present."""
        entries = self._get_warm_xprompt_arg_assist_entries()
        if entries is not None:
            return build_xprompt_completion_candidates(token, entries=entries)
        return build_xprompt_completion_candidates(token)
