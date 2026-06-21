"""VCS xprompt MRU cycling helpers for PromptTextArea."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.xprompt._parsing import (
    find_vcs_workflow_tag_prepend_offset,
    find_vcs_workflow_tag_span,
    normalize_vcs_underscore_refs,
)

VcsMruCycleKey = Literal["ctrl+n", "ctrl+p"]


@dataclass(frozen=True)
class _VcsMruCycleEdit:
    """Text edit produced by a VCS MRU cycle key."""

    text: str
    cursor_offset: int
    mru_index: int
    start_offset: int
    end_offset: int
    replacement: str


def _cycle_direction(key: VcsMruCycleKey) -> int:
    return -1 if key == "ctrl+n" else 1


def _normalize_mru_lookup_key(tag: str) -> str:
    return normalize_vcs_underscore_refs(tag.strip())


def _next_vcs_mru_index(
    *,
    mru: Sequence[str],
    key: VcsMruCycleKey,
    current_index: int | None,
    current_tag: str | None,
) -> int | None:
    """Return the next MRU index for a cycle keypress."""
    if not mru:
        return None

    direction = _cycle_direction(key)
    if current_index is not None:
        return (current_index + direction) % len(mru)

    if current_tag is not None:
        normalized_current = _normalize_mru_lookup_key(current_tag)
        normalized_mru = [_normalize_mru_lookup_key(entry) for entry in mru]
        if normalized_current in normalized_mru:
            base = normalized_mru.index(normalized_current)
            return (base + direction) % len(mru)

    return 0 if direction == 1 else len(mru) - 1


def _cursor_after_replacement(
    *,
    cursor_offset: int,
    start_offset: int,
    end_offset: int,
    replacement_len: int,
    snap_offset: int,
) -> int:
    if cursor_offset < start_offset:
        return cursor_offset
    if cursor_offset < end_offset:
        return snap_offset
    return cursor_offset + replacement_len - (end_offset - start_offset)


def _cycle_vcs_mru_text(
    *,
    text: str,
    cursor_offset: int,
    mru: Sequence[str],
    key: VcsMruCycleKey,
    current_index: int | None,
) -> _VcsMruCycleEdit | None:
    """Return the text edit for applying a VCS MRU cycle keypress."""
    span = None if not text.strip() else find_vcs_workflow_tag_span(text)
    current_tag = None if span is None else text[span[0] : span[1]]
    new_index = _next_vcs_mru_index(
        mru=mru,
        key=key,
        current_index=current_index,
        current_tag=current_tag,
    )
    if new_index is None:
        return None

    entry = mru[new_index]
    if not entry.strip():
        return None

    if not text.strip():
        replacement = f"{entry} "
        return _VcsMruCycleEdit(
            text=replacement,
            cursor_offset=len(replacement),
            mru_index=new_index,
            start_offset=0,
            end_offset=len(text),
            replacement=replacement,
        )

    if span is not None:
        start_offset, end_offset = span
        replacement = f"{entry} " if end_offset == len(text) else entry
        new_text = text[:start_offset] + replacement + text[end_offset:]
        new_cursor = _cursor_after_replacement(
            cursor_offset=cursor_offset,
            start_offset=start_offset,
            end_offset=end_offset,
            replacement_len=len(replacement),
            snap_offset=start_offset + len(entry),
        )
        return _VcsMruCycleEdit(
            text=new_text,
            cursor_offset=new_cursor,
            mru_index=new_index,
            start_offset=start_offset,
            end_offset=end_offset,
            replacement=replacement,
        )

    start_offset = end_offset = find_vcs_workflow_tag_prepend_offset(text)
    replacement = f"{entry} "
    new_text = text[:start_offset] + replacement + text[end_offset:]
    new_cursor = (
        cursor_offset
        if cursor_offset < start_offset
        else cursor_offset + len(replacement)
    )
    return _VcsMruCycleEdit(
        text=new_text,
        cursor_offset=new_cursor,
        mru_index=new_index,
        start_offset=start_offset,
        end_offset=end_offset,
        replacement=replacement,
    )


if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
    from textual.widgets._text_area import EditResult
else:
    _MixinBase = object


class VcsMruCyclingMixin(_MixinBase):
    """Mixin that applies VCS xprompt MRU cycling in the prompt widget."""

    if TYPE_CHECKING:
        _vcs_mru_index: int | None

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
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _on_prompt_completion_context_changed(self) -> None: ...

    def _handle_vcs_mru_cycle_key(self, key: VcsMruCycleKey) -> bool:
        """Apply a VCS MRU cycle keypress if one is available."""
        bar = self._find_prompt_bar()
        if bar is not None and bar._mode == "feedback":
            return False

        from sase.history.vcs_xprompt_mru import load_launchable_vcs_xprompt_mru

        edit = _cycle_vcs_mru_text(
            text=self.text,
            cursor_offset=self._absolute_offset(self.cursor_location),
            mru=load_launchable_vcs_xprompt_mru(),
            key=key,
            current_index=self._vcs_mru_index,
        )
        if edit is None:
            return False

        start = self._location_from_absolute(edit.start_offset)
        end = self._location_from_absolute(edit.end_offset)
        if self._replace_via_keyboard(edit.replacement, start, end) is None:
            return False

        self._vcs_mru_index = edit.mru_index
        self.move_cursor(self._location_from_absolute(edit.cursor_offset))
        self._clear_soft_completion(cancel_timer=True)
        self._clear_xprompt_arg_hint()
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()
        return True


__all__ = [
    "VcsMruCycleKey",
    "VcsMruCyclingMixin",
]
