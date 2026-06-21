"""Prompt-local deletion of the first VCS xprompt workflow tag.

The prompt ``Ctrl+N`` key removes the first real VCS workflow tag (e.g.
``#git:foo``) from the prompt body. Detection reuses
``find_vcs_workflow_tag_span`` so the deleted tag matches exactly what launch
parsing resolves -- in particular, tags quoted inside fenced code blocks are
skipped, making the keypress a no-op. The deletion runs as pure in-memory text
manipulation; it never loads MRU history or touches disk on the keypress path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.xprompt._parsing import find_vcs_workflow_tag_span


@dataclass(frozen=True)
class _VcsXPromptDeleteEdit:
    """Text edit that removes a VCS workflow tag from a prompt.

    ``[start_offset, end_offset)`` is the absolute range to delete (tag plus a
    cleaned-up separator); ``text`` is the full prompt after deletion and
    ``cursor_offset`` is where the cursor should land.
    """

    text: str
    cursor_offset: int
    start_offset: int
    end_offset: int


def _delete_vcs_xprompt_text(
    text: str,
    cursor_offset: int,
) -> _VcsXPromptDeleteEdit | None:
    """Return the edit deleting the first VCS workflow tag, or ``None``.

    Returns ``None`` when the prompt is blank or has no real VCS workflow tag
    (tags inside fenced blocks do not count). One adjacent separator is consumed
    so the deletion does not leave dangling whitespace:

    - a trailing space after the tag, or
    - the trailing newline when the tag is alone at the start of its line, or
    - otherwise a single leading space before the tag.
    """
    if not text.strip():
        return None
    span = find_vcs_workflow_tag_span(text)
    if span is None:
        return None

    start, end = span
    new_start, new_end = start, end
    trailing = text[end] if end < len(text) else None
    if trailing == " ":
        new_end = end + 1
    elif trailing == "\n" and (start == 0 or text[start - 1] == "\n"):
        new_end = end + 1
    elif start > 0 and text[start - 1] == " ":
        new_start = start - 1

    new_text = text[:new_start] + text[new_end:]
    removed = new_end - new_start
    if cursor_offset <= new_start:
        new_cursor = cursor_offset
    elif cursor_offset < new_end:
        new_cursor = new_start
    else:
        new_cursor = cursor_offset - removed
    new_cursor = min(new_cursor, len(new_text))

    return _VcsXPromptDeleteEdit(
        text=new_text,
        cursor_offset=new_cursor,
        start_offset=new_start,
        end_offset=new_end,
    )


if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
    from textual.widgets._text_area import EditResult
else:
    _MixinBase = object


class VcsXPromptDeleteMixin(_MixinBase):
    """Mixin that deletes the first VCS xprompt tag in the prompt widget."""

    if TYPE_CHECKING:
        text: str
        cursor_location: tuple[int, int]

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...

        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> EditResult | None: ...

        def move_cursor(
            self,
            location: tuple[int, int],
            select: bool = False,
            center: bool = False,
            record_width: bool = True,
        ) -> None: ...

        def _clear_soft_completion(self, *, cancel_timer: bool = False) -> None: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _on_prompt_completion_context_changed(self) -> None: ...

    def _handle_vcs_xprompt_delete_key(self) -> bool:
        """Delete the first VCS workflow tag from the prompt, if present.

        Returns ``True`` when a tag was deleted, ``False`` when there is nothing
        to delete (blank prompt, no tag, or only a fenced-block tag) or while the
        prompt bar is in feedback mode.
        """
        bar = self._find_prompt_bar()
        if bar is not None and bar._mode == "feedback":
            return False

        edit = _delete_vcs_xprompt_text(
            self.text,
            self._absolute_offset(self.cursor_location),
        )
        if edit is None:
            return False

        start = self._location_from_absolute(edit.start_offset)
        end = self._location_from_absolute(edit.end_offset)
        if self._replace_via_keyboard("", start, end) is None:
            return False

        self.move_cursor(self._location_from_absolute(edit.cursor_offset))
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
        return True


__all__ = [
    "VcsXPromptDeleteMixin",
]
