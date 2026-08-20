"""Shared data models for prompt stack actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptFocusRestore:
    """Exact pane focus state restored after a temporary pane closes."""

    item_id: str
    cursor: tuple[int, int]
    vim_mode: str


def stash_cursor_for_stripped_text(
    text: str, cursor: tuple[int, int]
) -> tuple[int, int]:
    """Map *cursor* in *text* onto coordinates of the persisted ``text.strip()``.

    Stash bodies drop surrounding whitespace. Convert through an absolute
    character offset so a multiline caret stays on the same logical character,
    and clamp carets that sat in the removed prefix or suffix to the start or
    end of the stored body.
    """
    stripped = text.strip()
    if not stripped:
        return (0, 0)
    offset = _cursor_to_offset(text, cursor)
    prefix_len = len(text) - len(text.lstrip())
    body_end = prefix_len + len(stripped)
    if offset <= prefix_len:
        new_offset = 0
    elif offset >= body_end:
        new_offset = len(stripped)
    else:
        new_offset = offset - prefix_len
    return _offset_to_cursor(stripped, new_offset)


def _cursor_to_offset(text: str, cursor: tuple[int, int]) -> int:
    if not text:
        return 0
    lines = text.split("\n")
    row, column = cursor
    row = max(0, min(row, len(lines) - 1))
    line = lines[row]
    column = max(0, min(column, len(line)))
    offset = 0
    for index in range(row):
        offset += len(lines[index]) + 1
    return offset + column


def _offset_to_cursor(text: str, offset: int) -> tuple[int, int]:
    if not text:
        return (0, 0)
    offset = max(0, min(offset, len(text)))
    lines = text.split("\n")
    remaining = offset
    for index, line in enumerate(lines):
        if remaining <= len(line):
            return (index, remaining)
        remaining -= len(line) + 1
    last = len(lines) - 1
    return (last, len(lines[last]))


@dataclass(frozen=True)
class StashedPromptPane:
    """One captured prompt-bar pane handed to the app for persistence.

    The bar captures presentation-side state only (the stripped pane ``text``,
    the bar's shared YAML ``frontmatter``, the pane's original ``pane_index``,
    and optional active-pane cursor metadata); the app layer enriches it with
    id / timestamp / project before writing through ``prompt_stash_facade``
    (boundary rule D6).
    """

    text: str
    frontmatter: str = ""
    pane_index: int = 0
    cursor: tuple[int, int] | None = None
    active: bool = False


@dataclass(frozen=True)
class PromptGPrefixHintEntry:
    """One currently available prompt ``g`` prefix hint."""

    key: str
    label: str
    aliases: tuple[str, ...] = ()
