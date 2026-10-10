"""Host-owned ``in:`` token helpers for Agents-tab and CLI query scope.

These helpers have no Textual imports. ``in:`` is a view-scope token, not a
row-matching field: extract it before dialect parse / Rust eval.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal

from sase.filter_tokens import FilterQueryError

HOST_SCOPE_KEY = "in"
HOST_SCOPE_HINT = "inbox or archive"
HOST_SCOPE_VALUE_HINT = "inbox or archive"
HOST_SCOPE_VALUES = ("inbox", "archive")

_ScopeValue = Literal["inbox", "archive"]
_LexKind = Literal[
    "and",
    "or",
    "not",
    "lparen",
    "rparen",
    "property",
    "string",
    "other",
]


class ScopeTokenError(FilterQueryError):
    """A host-owned ``in:`` token parse failure tied to an exact span."""


@dataclass(frozen=True, slots=True)
class _Lexeme:
    kind: _LexKind
    raw: str
    start: int
    end: int
    key: str | None = None
    value: str | None = None
    negated: bool = False


def extract_scope(query: str) -> tuple[str, _ScopeValue | None]:
    """Return ``(remainder, scope)`` after removing a host ``in:`` token.

    ``None`` means the inbox default: the token is absent. Duplicate, nested,
    negated, empty, and unknown values raise :class:`ScopeTokenError`.
    """
    token, scope, cut_spans = _scan_scope(query)
    if token is None:
        return query, None
    return _cut_spans(query, cut_spans), scope


def check_scope_fields(remainder: str, scope: _ScopeValue | None) -> None:
    """Raise a scope-hint error when *remainder* uses the other view's fields."""

    try:
        events = _lex(remainder)
    except ScopeTokenError:
        return
    archive_only = _archive_only_keys()
    inbox_only = _inbox_only_keys()
    for event in events:
        if event.kind != "property" or event.key is None:
            continue
        key = event.key
        if scope == "archive" and key in inbox_only:
            raise _error(_inbox_field_hint(key), event.start, event.end, event.raw)
        if scope != "archive" and key in archive_only:
            raise _error(_archive_field_hint(key), event.start, event.end, event.raw)


def _drop_archive_only_fields(query: str) -> str:
    """Remove archive-only ``key:value`` terms from an inbox membership query."""

    if not query.strip():
        return query
    try:
        events, depths = _lex_with_depth(query)
    except ScopeTokenError:
        return query
    archive_only = _archive_only_keys()
    spans = _field_cut_spans(events, depths, archive_only)
    if not spans:
        return query
    return _cut_spans(query, spans)


def _archive_field_hint(field: str) -> str:
    """Return the Inbox-side hint for an Archive-only *field*."""

    return f"{field}: is an Archive field · add in:archive or press ,a"


def _inbox_field_hint(field: str) -> str:
    """Return the Archive-side hint for an Inbox-only *field*."""

    return f"{field}: is an Inbox field · remove in:archive or press ,a"


def inbox_membership_query(query: str) -> tuple[str, _ScopeValue | None]:
    """Extract ``in:``, enforce scope hints, and drop archive-only inbox terms.

    Returns ``(membership_query, scope)``. An empty membership query means
    "match every inbox row".
    """
    remainder, scope = extract_scope(query)
    check_scope_fields(remainder, scope)
    return _drop_archive_only_fields(remainder), scope


@cache
def _archive_only_keys() -> frozenset[str]:
    return _exclusive_keys("archive")


@cache
def _inbox_only_keys() -> frozenset[str]:
    return _exclusive_keys("inbox")


def _exclusive_keys(side: Literal["archive", "inbox"]) -> frozenset[str]:
    from sase.ace.query_profile.profiles._agents_archive import (
        agents_archive_query_schema,
    )
    from sase.ace.query_profile.profiles._agents_live import agents_live_query_schema

    archive = {item.key for item in agents_archive_query_schema().fields}
    live = {item.key for item in agents_live_query_schema().fields}
    if side == "archive":
        return frozenset(archive - live)
    return frozenset(live - archive)


def _scan_scope(
    query: str,
) -> tuple[_Lexeme | None, _ScopeValue | None, tuple[tuple[int, int], ...]]:
    events, depths = _lex_with_depth(query)
    found: _Lexeme | None = None
    found_index: int | None = None
    found_depth: int | None = None
    has_top_level_or = False
    pending_not: set[int] = set()
    for index, (event, depth) in enumerate(zip(events, depths, strict=True)):
        if event.kind == "or" and depth == 0:
            has_top_level_or = True
        if event.kind == "not":
            pending_not.add(depth)
            continue
        if event.kind == "property" and event.key == HOST_SCOPE_KEY:
            _validate_in_token(event, pending_not=depth in pending_not)
            if found is not None:
                raise _error(
                    "in: may only appear once", event.start, event.end, event.raw
                )
            found = event
            found_index = index
            found_depth = depth
            pending_not.discard(depth)
            continue
        if event.kind in {"property", "string", "other", "lparen"}:
            pending_not.discard(depth)
    if found is None or found_index is None or found_depth is None:
        return None, None, ()
    if found_depth > 0:
        raise _error(
            "in: may not appear inside parentheses",
            found.start,
            found.end,
            found.raw,
        )
    if has_top_level_or:
        raise _error(
            "in: may not appear inside OR",
            found.start,
            found.end,
            found.raw,
        )
    assert found.value is not None
    scope: _ScopeValue = found.value.casefold()  # type: ignore[assignment]
    spans = _scope_cut_spans(events, depths, found_index, found_depth)
    return found, scope, spans


def _validate_in_token(event: _Lexeme, *, pending_not: bool) -> None:
    if event.negated:
        raise _error("in: may not be negated", event.start, event.end, event.raw)
    if pending_not:
        raise _error(
            "in: may not appear inside NOT",
            event.start,
            event.end,
            event.raw,
        )
    if event.value is None or event.value == "":
        raise _error("in: requires a value", event.start, event.end, event.raw)
    if event.value.casefold() not in HOST_SCOPE_VALUES:
        raise _error(
            "in: must be 'inbox' or 'archive'",
            event.start,
            event.end,
            event.raw,
        )


def _scope_cut_spans(
    events: tuple[_Lexeme, ...],
    depths: tuple[int, ...],
    index: int,
    depth: int,
) -> tuple[tuple[int, int], ...]:
    spans = [(events[index].start, events[index].end)]
    prev_index = index - 1
    next_index = index + 1
    if (
        prev_index >= 0
        and events[prev_index].kind == "and"
        and depths[prev_index] == depth
    ):
        spans.append((events[prev_index].start, events[prev_index].end))
    elif (
        next_index < len(events)
        and events[next_index].kind == "and"
        and depths[next_index] == depth
    ):
        spans.append((events[next_index].start, events[next_index].end))
    return tuple(spans)


def _field_cut_spans(
    events: tuple[_Lexeme, ...],
    depths: tuple[int, ...],
    keys: frozenset[str],
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for index, event in enumerate(events):
        if event.kind != "property" or event.key not in keys:
            continue
        spans.append((event.start, event.end))
        depth = depths[index]
        prev_index = index - 1
        next_index = index + 1
        if (
            prev_index >= 0
            and events[prev_index].kind == "and"
            and depths[prev_index] == depth
        ):
            spans.append((events[prev_index].start, events[prev_index].end))
        elif (
            next_index < len(events)
            and events[next_index].kind == "and"
            and depths[next_index] == depth
        ):
            spans.append((events[next_index].start, events[next_index].end))
    return tuple(spans)


def _lex_with_depth(query: str) -> tuple[tuple[_Lexeme, ...], tuple[int, ...]]:
    events = _lex(query)
    depths: list[int] = []
    depth = 0
    for event in events:
        if event.kind == "lparen":
            depths.append(depth)
            depth += 1
        elif event.kind == "rparen":
            depth = max(0, depth - 1)
            depths.append(depth)
        else:
            depths.append(depth)
    return events, tuple(depths)


def _lex(query: str) -> tuple[_Lexeme, ...]:
    events: list[_Lexeme] = []
    pos = 0
    length = len(query)
    while pos < length:
        while pos < length and query[pos].isspace():
            pos += 1
        if pos >= length:
            break
        char = query[pos]
        if char == '"':
            token, pos = _parse_quoted_string(query, pos)
            events.append(token)
        elif char == "c" and pos + 1 < length and query[pos + 1] == '"':
            token, pos = _parse_quoted_string(query, pos + 1, raw_prefix="c")
            events.append(token)
        elif char == "(":
            events.append(_Lexeme("lparen", "(", pos, pos + 1))
            pos += 1
        elif char == ")":
            events.append(_Lexeme("rparen", ")", pos, pos + 1))
            pos += 1
        elif char == "!":
            token, pos = _parse_bang(query, pos)
            events.append(token)
        elif char == "-":
            token, pos = _parse_leading_dash(query, pos)
            events.append(token)
        elif _is_word_start(char):
            token, pos = _parse_word_or_property(query, pos)
            events.append(token)
        else:
            events.append(_Lexeme("other", char, pos, pos + 1))
            pos += 1
    return tuple(events)


def _parse_bang(query: str, pos: int) -> tuple[_Lexeme, int]:
    if query[pos : pos + 3] == "!!!":
        return _Lexeme("other", "!!!", pos, pos + 3), pos + 3
    if query[pos : pos + 2] in {"!!", "!@", "!$"} and _standalone_at(query, pos + 2):
        raw = query[pos : pos + 2]
        return _Lexeme("other", raw, pos, pos + 2), pos + 2
    if _standalone_at(query, pos + 1):
        return _Lexeme("other", "!", pos, pos + 1), pos + 1
    return _Lexeme("not", "!", pos, pos + 1), pos + 1


def _parse_leading_dash(query: str, pos: int) -> tuple[_Lexeme, int]:
    next_pos = pos + 1
    if next_pos < len(query) and _is_word_start(query[next_pos]):
        token, end = _parse_word_or_property(query, next_pos)
        if token.kind == "property":
            raw = query[pos:end]
            return (
                _Lexeme(
                    "property",
                    raw,
                    pos,
                    end,
                    key=token.key,
                    value=token.value,
                    negated=True,
                ),
                end,
            )
    return _Lexeme("other", "-", pos, pos + 1), pos + 1


def _parse_word_or_property(query: str, pos: int) -> tuple[_Lexeme, int]:
    start = pos
    length = len(query)
    while pos < length and _is_word_char(query[pos]):
        pos += 1
    word = query[start:pos]
    upper = word.upper()
    if upper == "AND":
        return _Lexeme("and", word, start, pos), pos
    if upper == "OR":
        return _Lexeme("or", word, start, pos), pos
    if upper == "NOT":
        return _Lexeme("not", word, start, pos), pos
    if pos < length and query[pos] == ":":
        key = word.casefold()
        pos += 1
        if pos >= length or query[pos].isspace() or query[pos] in "()":
            raw = query[start:pos]
            return (
                _Lexeme("property", raw, start, pos, key=key, value=""),
                pos,
            )
        value, pos = _parse_property_value(query, pos, extended=key == "artifact")
        raw = query[start:pos]
        return (
            _Lexeme("property", raw, start, pos, key=key, value=value),
            pos,
        )
    return _Lexeme("string", word, start, pos), pos


def _parse_property_value(
    query: str,
    pos: int,
    *,
    extended: bool,
) -> tuple[str, int]:
    if pos < len(query) and query[pos] == '"':
        token, next_pos = _parse_quoted_string(query, pos)
        return token.raw[1:-1] if token.raw.endswith('"') else token.raw[1:], next_pos
    start = pos
    length = len(query)
    if extended:
        while pos < length and not query[pos].isspace() and query[pos] not in "()":
            pos += 1
    else:
        while pos < length and _is_value_char(query[pos]):
            pos += 1
    return query[start:pos], pos


def _parse_quoted_string(
    query: str,
    pos: int,
    *,
    raw_prefix: str = "",
) -> tuple[_Lexeme, int]:
    start = pos - len(raw_prefix)
    pos += 1
    while pos < len(query):
        char = query[pos]
        if char == '"':
            end = pos + 1
            return _Lexeme("string", query[start:end], start, end), end
        if char == "\\" and pos + 1 < len(query):
            pos += 2
            continue
        pos += 1
    raise _error(
        "Unterminated double quote",
        start,
        len(query),
        query[start:],
    )


def _cut_spans(query: str, spans: Sequence[tuple[int, int]]) -> str:
    if not spans:
        return query
    ordered = sorted(spans)
    pieces: list[str] = []
    cursor = 0
    for start, end in ordered:
        if end <= cursor:
            continue
        if start > cursor:
            pieces.append(query[cursor:start])
        cursor = max(cursor, end)
    pieces.append(query[cursor:])
    return " ".join("".join(pieces).split())


def _standalone_at(query: str, pos: int) -> bool:
    return pos >= len(query) or query[pos].isspace()


def _is_word_start(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char in "_.-"


def _is_value_char(char: str) -> bool:
    return char.isalnum() or char in "_.-*"


def _error(message: str, start: int, end: int, token: str) -> ScopeTokenError:
    return ScopeTokenError(message, token=token, start=start, end=end)


__all__ = [
    "HOST_SCOPE_HINT",
    "HOST_SCOPE_KEY",
    "HOST_SCOPE_VALUE_HINT",
    "HOST_SCOPE_VALUES",
    "ScopeTokenError",
    "check_scope_fields",
    "extract_scope",
    "inbox_membership_query",
]
