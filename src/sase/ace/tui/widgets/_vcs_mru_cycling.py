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


def _current_workspace_target_span(
    text: str,
    catalog: Any | None = None,
) -> tuple[int, int] | None:
    """Return the span of the prompt's leading workspace target, if any.

    A workspace target is either a ``#`` VCS workflow ref (found with the
    shared span helper, literal zones excluded) or a ``+<project>`` tag:
    with a catalog, the first scanned tag that names a known target; with
    a cold catalog (``None``), the first scanned anchored tag, since
    anchored tags are always intended targets (D3) while unanchored
    unknowns are plain text. The earliest span wins; a tie keeps the ref.
    """
    ref_span = None
    if text.strip():
        ref_span = find_vcs_workflow_tag_span(text)
    tag_span = _current_project_tag_span(text, catalog)
    if tag_span is None:
        return ref_span
    if ref_span is None or tag_span[0] > ref_span[0]:
        return ref_span if ref_span is not None else tag_span
    if tag_span[0] < ref_span[0]:
        return tag_span
    return ref_span


def _current_project_tag_span(
    text: str,
    catalog: Any | None,
) -> tuple[int, int] | None:
    """Return the span of the first tag that counts as a workspace target."""
    if "+" not in text:
        return None
    try:
        from sase.project_tags import find_project_tags
    except Exception:  # noqa: BLE001 - cycling degrades to ref-only.
        return None
    try:
        scanned = find_project_tags(text)
    except Exception:  # noqa: BLE001 - cycling degrades to ref-only.
        return None
    for found in scanned:
        if not isinstance(found, dict):
            continue
        try:
            raw_start = found["start"]
            raw_end = found["end"]
            raw_name = found["name"]
            raw_anchored = found["anchored"]
        except KeyError:
            continue
        if (
            not isinstance(raw_start, int)
            or not isinstance(raw_end, int)
            or not isinstance(raw_name, str)
        ):
            continue
        start, end = raw_start, raw_end
        name, anchored = raw_name, bool(raw_anchored)
        if catalog is not None:
            if _catalog_names_target(catalog, name):
                return (start, end)
        elif anchored:
            return (start, end)
    return None


def _catalog_names_target(catalog: Any, name: str) -> bool:
    """Return whether *name* matches a catalog target (case-insensitive)."""
    folded = name.casefold()
    for target in catalog.targets:
        candidates = [target.key, target.name, *target.aliases]
        if any(candidate.casefold() == folded for candidate in candidates):
            return True
    return False


def _mru_entry_display_form(entry: str, catalog: Any | None) -> str:
    """Return the MRU entry's display form: a tag for projects (D7).

    Patch entries and entries for unknown projects keep their ``#`` ref;
    a cold catalog (``None``) leaves every entry unchanged.
    """
    if catalog is None:
        return entry
    from sase.project_tags import known_project_tag_for
    from sase.xprompt import extract_project_from_vcs_tag

    project = extract_project_from_vcs_tag(entry)
    if not project:
        return entry
    spelling = known_project_tag_for(catalog, project)
    if spelling is not None and spelling.startswith("+"):
        return spelling
    return entry


#: The two prompt keys that drive VCS xprompt MRU cycling. ``ctrl+p`` cycles
#: forward (toward older entries) and ``ctrl+n`` cycles backward (toward newer
#: entries); both share one ring whose terminal stop clears the VCS tag.
VcsMruCycleKey = Literal["ctrl+n", "ctrl+p"]

_VCS_MRU_CYCLE_DIRECTION: dict[VcsMruCycleKey, int] = {
    "ctrl+p": 1,
    "ctrl+n": -1,
}


@dataclass(frozen=True)
class _VcsMruCycleEdit:
    """Text edit produced by a VCS MRU cycle key."""

    text: str
    cursor_offset: int
    mru_index: int
    start_offset: int
    end_offset: int
    replacement: str


@dataclass(frozen=True)
class _VcsXPromptDeleteEdit:
    """Text edit that removes a VCS workflow tag from a prompt."""

    text: str
    cursor_offset: int
    start_offset: int
    end_offset: int


def _delete_vcs_xprompt_text(
    text: str,
    cursor_offset: int,
    catalog: Any | None = None,
) -> _VcsXPromptDeleteEdit | None:
    """Return the edit deleting the leading workspace target, or ``None``.

    The target is a ``#`` VCS workflow tag or a ``+<project>`` tag (see
    :func:`_current_workspace_target_span`). One adjacent separator is
    consumed with the target so deletion does not leave dangling whitespace.
    """
    if not text.strip():
        return None
    span = _current_workspace_target_span(text, catalog)
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


def _normalize_mru_lookup_key(tag: str) -> str:
    return normalize_vcs_underscore_refs(tag.strip())


def _next_vcs_mru_index(
    *,
    mru: Sequence[str],
    current_index: int | None,
    current_tag: str | None,
    direction: int,
    catalog: Any | None = None,
) -> int | None:
    """Return the next MRU index for a directional cycle keypress.

    ``direction`` is ``+1`` for a forward (``ctrl+p``) cycle and ``-1`` for a
    backward (``ctrl+n``) cycle. The ring includes one terminal empty position
    at ``len(mru)``; moving onto it clears the workspace target. When the
    prompt has no workspace target, a forward cycle starts at the most recent
    entry (index ``0``) and a backward cycle starts at the oldest entry
    (index ``len(mru) - 1``). Both the current target and the ring compare
    in display form (a tag for projects), so ``+sase`` resumes the ring at
    a ``#gh:sase`` entry.
    """
    if not mru:
        return None

    ring_len = len(mru) + 1
    if current_index is not None:
        return (current_index + direction) % ring_len

    if current_tag is not None:
        normalized_current = _normalize_mru_lookup_key(
            _mru_entry_display_form(current_tag, catalog)
        )
        normalized_mru = [
            _normalize_mru_lookup_key(_mru_entry_display_form(entry, catalog))
            for entry in mru
        ]
        if normalized_current in normalized_mru:
            base = normalized_mru.index(normalized_current)
            return (base + direction) % ring_len

    return 0 if direction > 0 else len(mru) - 1


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
    current_index: int | None,
    key: VcsMruCycleKey = "ctrl+p",
    catalog: Any | None = None,
) -> _VcsMruCycleEdit | None:
    """Return the text edit for applying a directional VCS MRU cycle keypress.

    The current leading workspace target may be a ``+<project>`` tag or a
    ``#`` ref; the replacement is the next MRU entry's display form (a tag
    for projects). *catalog* is the tag snapshot used for both; ``None``
    (cold) keeps every entry in its stored form.
    """
    span = None if not text.strip() else _current_workspace_target_span(text, catalog)
    current_tag = None if span is None else text[span[0] : span[1]]
    new_index = _next_vcs_mru_index(
        mru=mru,
        current_index=current_index,
        current_tag=current_tag,
        direction=_VCS_MRU_CYCLE_DIRECTION[key],
        catalog=catalog,
    )
    if new_index is None:
        return None

    if new_index == len(mru):
        delete_edit = _delete_vcs_xprompt_text(text, cursor_offset, catalog)
        if delete_edit is None:
            return None
        return _VcsMruCycleEdit(
            text=delete_edit.text,
            cursor_offset=delete_edit.cursor_offset,
            mru_index=new_index,
            start_offset=delete_edit.start_offset,
            end_offset=delete_edit.end_offset,
            replacement="",
        )

    entry = _mru_entry_display_form(mru[new_index], catalog)
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
        """Apply a directional VCS MRU cycle keypress if one is available.

        ``ctrl+p`` cycles forward and ``ctrl+n`` cycles backward through the
        shared ring; reaching the ring's empty stop clears the workspace
        target. The current target may be a tag or a ref, and replacements
        use the tag display form for projects. A cold tag catalog degrades
        to the stored MRU spellings.
        """
        bar = self._find_prompt_bar()
        if bar is not None and bar._mode == "feedback":
            return False

        from sase.history.vcs_xprompt_mru import load_launchable_vcs_xprompt_mru
        from sase.project_tags import peek_project_tag_catalog

        edit = _cycle_vcs_mru_text(
            text=self.text,
            cursor_offset=self._absolute_offset(self.cursor_location),
            mru=load_launchable_vcs_xprompt_mru(),
            current_index=self._vcs_mru_index,
            key=key,
            catalog=peek_project_tag_catalog(),
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
