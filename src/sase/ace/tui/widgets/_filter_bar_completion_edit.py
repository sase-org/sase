"""Text insertion primitives for filter-bar completions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterCompletionMetadata:
    """Insertion and presentation data attached to a completion row."""

    kind: str
    value: str
    hint: str
    append_space: bool = True
    selectable: bool = True
    repeatable: bool = False


def apply_filter_completion(
    text: str,
    cursor: int,
    metadata: FilterCompletionMetadata,
) -> tuple[str, int]:
    """Replace the active query token with the selected completion value."""
    cursor = min(max(cursor, 0), len(text))
    token_start, token_end = _token_bounds(text, cursor)
    if metadata.kind == "key":
        start = token_start
        insertion = metadata.value
    elif metadata.kind.startswith("sigil:"):
        start = min(token_start + 1, cursor)
        insertion = _quote_completion_value(metadata.value)
    else:
        colon = _first_unquoted(text, token_start, cursor, ":")
        if colon is None:
            start = token_start
            insertion = metadata.value
        else:
            start = colon + 1
            if metadata.repeatable:
                comma = _last_unquoted(text, start, cursor, ",")
                if comma is not None:
                    start = comma + 1
            insertion = _quote_completion_value(metadata.value)

    end = token_end
    if metadata.append_space:
        if end < len(text) and text[end].isspace():
            end += 1
        insertion = f"{insertion} "
    completed = f"{text[:start]}{insertion}{text[end:]}"
    return completed, start + len(insertion)


def _token_bounds(text: str, cursor: int) -> tuple[int, int]:
    in_quotes = False
    start = 0
    for index, char in enumerate(text[:cursor]):
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char.isspace() and not in_quotes:
            start = index + 1

    end = cursor
    for index in range(cursor, len(text)):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char.isspace() and not in_quotes:
            end = index
            break
    else:
        end = len(text)
    return start, end


def _first_unquoted(text: str, start: int, end: int, needle: str) -> int | None:
    in_quotes = False
    for index in range(start, end):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char == needle and not in_quotes:
            return index
    return None


def _last_unquoted(text: str, start: int, end: int, needle: str) -> int | None:
    in_quotes = False
    found: int | None = None
    for index in range(start, end):
        char = text[index]
        if char == '"' and not _is_escaped(text, index):
            in_quotes = not in_quotes
        elif char == needle and not in_quotes:
            found = index
    return found


def _is_escaped(text: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 1


def _quote_completion_value(value: str) -> str:
    if not any(char.isspace() or char in {",", '"', "\\"} for char in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


__all__ = ["FilterCompletionMetadata", "apply_filter_completion"]
