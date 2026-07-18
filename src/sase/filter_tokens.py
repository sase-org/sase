"""Shared lexical helpers for inline token filter languages."""

from __future__ import annotations

import difflib
from collections.abc import Collection, Iterable
from dataclasses import dataclass


class FilterQueryError(ValueError):
    """A query parse failure tied to an exact token span."""

    def __init__(self, message: str, *, token: str, start: int, end: int) -> None:
        super().__init__(message)
        self.message = message
        self.token = token
        self.bad_token = token
        self.start = start
        self.end = end
        self.span = (start, end)


@dataclass(frozen=True)
class FilterToken:
    """One decoded query token together with its source coordinates."""

    value: str
    raw: str
    start: int
    end: int
    quoted: tuple[bool, ...]
    wholly_quoted: bool


def tokenize(
    text: str,
    *,
    strict: bool = True,
    error_type: type[FilterQueryError] = FilterQueryError,
) -> tuple[FilterToken, ...]:
    """Decode whitespace-separated tokens with double-quote preservation."""
    tokens: list[FilterToken] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        start = index
        value: list[str] = []
        quoted: list[bool] = []
        in_quotes = False
        saw_quote = False
        saw_unquoted = False
        while index < len(text):
            char = text[index]
            if not in_quotes and char.isspace():
                break
            if char == '"':
                saw_quote = True
                in_quotes = not in_quotes
                index += 1
                continue
            if in_quotes and char == "\\" and index + 1 < len(text):
                escaped = text[index + 1]
                if escaped in {'"', "\\"}:
                    value.append(escaped)
                    quoted.append(True)
                    index += 2
                    continue
            value.append(char)
            quoted.append(in_quotes)
            if not in_quotes:
                saw_unquoted = True
            index += 1
        end = index
        raw = text[start:end]
        if in_quotes and strict:
            raise error_type(
                "Unterminated double quote",
                token=raw,
                start=start,
                end=end,
            )
        tokens.append(
            FilterToken(
                value="".join(value),
                raw=raw,
                start=start,
                end=end,
                quoted=tuple(quoted),
                wholly_quoted=saw_quote and not saw_unquoted,
            )
        )
    return tuple(tokens)


def completion_context(
    text: str,
    cursor: int,
    *,
    keys: Collection[str],
    repeatable_keys: Collection[str],
) -> tuple[str, str]:
    """Classify and decode the token prefix immediately before *cursor*."""
    cursor = min(max(cursor, 0), len(text))
    prefix_text = text[:cursor]
    if not prefix_text or prefix_text[-1].isspace():
        return ("key", "")
    tokens = tokenize(prefix_text, strict=False)
    if not tokens:
        return ("key", "")
    token = tokens[-1]
    if token.wholly_quoted:
        return ("text", token.value)
    colon = unquoted_index(token, ":")
    if colon < 0:
        return ("key", token.value)
    key = token.value[:colon].casefold()
    if key not in keys:
        return ("key", token.value)
    value = token.value[colon + 1 :]
    quoted = token.quoted[colon + 1 :]
    if key in repeatable_keys:
        comma = _last_unquoted_index(value, quoted, ",")
        if comma >= 0:
            value = value[comma + 1 :]
    return (key, value)


def error_for_token(
    message: str,
    token: FilterToken,
    *,
    error_type: type[FilterQueryError] = FilterQueryError,
) -> FilterQueryError:
    """Build a span-carrying error for *token*."""
    return error_type(
        message,
        token=token.raw,
        start=token.start,
        end=token.end,
    )


def unknown_key_error(
    key: str,
    token: FilterToken,
    *,
    keys: Iterable[str],
    error_type: type[FilterQueryError] = FilterQueryError,
) -> FilterQueryError:
    """Build an unknown-key error, including a close-match suggestion."""
    key_options = tuple(keys)
    suggestion = difflib.get_close_matches(key, key_options, n=1, cutoff=0.55)
    message = f"Unknown filter key {key!r}"
    if suggestion:
        message += f"; did you mean '{suggestion[0]}:'?"
    return error_for_token(message, token, error_type=error_type)


def unquoted_index(token: FilterToken, character: str) -> int:
    """Return the first unquoted *character* offset, or ``-1``."""
    return next(
        (
            index
            for index, value in enumerate(token.value)
            if value == character and not token.quoted[index]
        ),
        -1,
    )


def _last_unquoted_index(
    value: str,
    quoted: tuple[bool, ...],
    character: str,
) -> int:
    """Return the last unquoted *character* offset, or ``-1``."""
    return next(
        (
            index
            for index in range(len(value) - 1, -1, -1)
            if value[index] == character and not quoted[index]
        ),
        -1,
    )


def split_unquoted(
    value: str,
    quoted: tuple[bool, ...],
    separator: str,
) -> tuple[str, ...]:
    """Split *value* at unquoted occurrences of *separator*."""
    parts: list[str] = []
    start = 0
    for index, char in enumerate(value):
        if char == separator and not quoted[index]:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return tuple(parts)


def quote_value(value: str, *, keyed: bool) -> str:
    """Quote one decoded value only when token parsing requires it."""
    needs_quotes = (
        not value
        or any(char.isspace() or char == '"' for char in value)
        or (keyed and "," in value)
        or (not keyed and ":" in value)
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


__all__ = [
    "FilterQueryError",
    "FilterToken",
    "completion_context",
    "error_for_token",
    "quote_value",
    "split_unquoted",
    "tokenize",
    "unknown_key_error",
    "unquoted_index",
]
