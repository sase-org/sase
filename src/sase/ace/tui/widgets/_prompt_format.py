"""Explicit asynchronous Markdown formatting for ``PromptTextArea``."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from textual.document._document import EditResult, Selection

from sase.file_references import format_agent_prompt_markdown

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


type _DiffOpcode = tuple[str, int, int, int, int]


@dataclass(frozen=True)
class _PromptFormatResult:
    """Formatted text plus the diff needed to preserve live cursor state."""

    text: str
    opcodes: tuple[_DiffOpcode, ...]


def _format_prompt_and_diff(source: str) -> _PromptFormatResult:
    """Format *source* and build its character-level offset mapping off-thread."""
    formatted = format_agent_prompt_markdown(source)
    if formatted == source:
        return _PromptFormatResult(formatted, ())
    matcher = SequenceMatcher(None, source, formatted, autojunk=False)
    return _PromptFormatResult(formatted, tuple(matcher.get_opcodes()))


def _map_prompt_offset(
    offset: int,
    *,
    source_length: int,
    formatted_length: int,
    opcodes: tuple[_DiffOpcode, ...],
) -> int:
    """Map a character-boundary offset through a source/formatting diff.

    Equal content retains its exact logical position. Positions within replaced
    whitespace are mapped proportionally, while insertions at a boundary stay
    attached to the following source character. The document-end boundary maps
    to the new document end, including Prettier's conventional final newline.
    """
    offset = max(0, min(offset, source_length))
    if offset == source_length:
        return formatted_length

    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "insert":
            if offset == old_start:
                return new_end
            continue
        if not old_start <= offset < old_end:
            continue
        if tag == "equal":
            return new_start + (offset - old_start)

        old_span = old_end - old_start
        new_span = new_end - new_start
        if old_span <= 0:
            return new_end
        relative = offset - old_start
        mapped = new_start + round(relative * new_span / old_span)
        return max(new_start, min(mapped, new_end))

    return formatted_length


class PromptFormatMixin(_MixinBase):
    """Widget-scoped, non-blocking prompt Markdown formatting lifecycle."""

    if TYPE_CHECKING:
        _prompt_format_request_id: int
        _dot_insert_capture_offset: int | None
        _mutation_key_buffer: list[str]
        _pending_optional_spacer: object | None
        _snippet_end_from_doc_end: int
        _snippet_tabstops: list[int]
        _vcs_mru_index: int | None
        _vim_mode: str
        _visual_anchor: tuple[int, int] | None
        _visual_cursor: tuple[int, int] | None

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_insert_g_prefix(self) -> None: ...
        def _clear_normal_g_prefix(self) -> None: ...
        def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None: ...
        def _clear_soft_completion(
            self,
            *,
            cancel_timer: bool = False,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> EditResult | None: ...
        def _update_visual_selection(self) -> None: ...

    def format_prompt_markdown(self) -> None:
        """Format this exact pane without blocking or retargeting on focus."""
        source = self.text
        if not source:
            return

        self._prompt_format_request_id += 1
        request_id = self._prompt_format_request_id
        origin_parent = self.parent

        # Formatting replaces the whole buffer, so dismiss transient surfaces
        # anchored to the old source before the worker starts.
        self._clear_insert_g_prefix()
        self._clear_normal_g_prefix()
        self._clear_file_completion()
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()
        self._clear_prompt_search(clear_highlights=True)
        self._snippet_tabstops = []
        self._snippet_end_from_doc_end = 0
        self._pending_optional_spacer = None
        self._vcs_mru_index = None
        # ``gf`` is an explicit editor command, not a repeatable Vim mutation.
        self._mutation_key_buffer.clear()

        self.run_worker(
            self._format_prompt_markdown_async(
                source,
                request_id=request_id,
                origin_parent=origin_parent,
            ),
            name=f"prompt-format:{request_id}",
        )

    async def _format_prompt_markdown_async(
        self,
        source: str,
        *,
        request_id: int,
        origin_parent: object,
    ) -> None:
        try:
            result = await asyncio.to_thread(_format_prompt_and_diff, source)
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._prompt_format_result_is_current(
                source,
                request_id=request_id,
                origin_parent=origin_parent,
            ):
                self.notify("Could not format prompt", severity="error")
            return

        if not self._prompt_format_result_is_current(
            source,
            request_id=request_id,
            origin_parent=origin_parent,
        ):
            return
        if result.text == source:
            self.notify("Formatting made no changes")
            return

        self._apply_formatted_prompt(source, result)

    def _prompt_format_result_is_current(
        self,
        source: str,
        *,
        request_id: int,
        origin_parent: object,
    ) -> bool:
        """Return whether a worker result still belongs to this live pane."""
        return (
            request_id == self._prompt_format_request_id
            and self.is_mounted
            and self.parent is origin_parent
            and self.text == source
        )

    def _apply_formatted_prompt(
        self,
        source: str,
        result: _PromptFormatResult,
    ) -> None:
        """Apply one whole-buffer edit while preserving live mode/selection."""
        selection = self.selection
        start_offset = self._absolute_offset(selection.start)
        end_offset = self._absolute_offset(selection.end)
        source_length = len(source)
        formatted_length = len(result.text)

        def map_offset(offset: int) -> int:
            return _map_prompt_offset(
                offset,
                source_length=source_length,
                formatted_length=formatted_length,
                opcodes=result.opcodes,
            )

        mapped_start = map_offset(start_offset)
        mapped_end = map_offset(end_offset)
        dot_capture_offset = self._dot_insert_capture_offset
        mapped_dot_capture = (
            map_offset(dot_capture_offset) if dot_capture_offset is not None else None
        )

        visual_offsets: tuple[int, int] | None = None
        if self._vim_mode in {"visual", "visual_line"}:
            anchor = self._visual_anchor
            cursor = self._visual_cursor
            if anchor is not None and cursor is not None:
                visual_offsets = (
                    map_offset(self._absolute_offset(anchor)),
                    map_offset(self._absolute_offset(cursor)),
                )

        last_row = self.document.line_count - 1
        document_end = (last_row, len(self.document.get_line(last_row)))
        was_read_only = self.read_only
        self.read_only = False
        try:
            edit_result = self._replace_via_keyboard(
                result.text,
                (0, 0),
                document_end,
            )
        finally:
            self.read_only = was_read_only
        if edit_result is None:
            return

        self._dot_insert_capture_offset = mapped_dot_capture
        if visual_offsets is not None:
            self._visual_anchor = self._location_from_absolute(visual_offsets[0])
            self._visual_cursor = self._location_from_absolute(visual_offsets[1])
            self._update_visual_selection()
        else:
            self.selection = Selection(
                self._location_from_absolute(mapped_start),
                self._location_from_absolute(mapped_end),
            )


__all__ = ["PromptFormatMixin"]
