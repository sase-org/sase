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
    negated: bool

    @property
    def body(self) -> str:
        """Return the decoded token after its optional negation marker."""
        return self.value[1:] if self.negated else self.value

    @property
    def body_quoted(self) -> tuple[bool, ...]:
        """Return quote metadata aligned with :attr:`body`."""
        return self.quoted[1:] if self.negated else self.quoted


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
        decoded = "".join(value)
        wholly_quoted = saw_quote and not saw_unquoted
        tokens.append(
            FilterToken(
                value=decoded,
                raw=raw,
                start=start,
                end=end,
                quoted=tuple(quoted),
                wholly_quoted=wholly_quoted,
                negated=bool(decoded)
                and decoded[0] == "-"
                and not quoted[0]
                and not wholly_quoted,
            )
        )
    return tuple(tokens)


def completion_context(
    text: str,
    cursor: int,
    *,
    keys: Collection[str],
    repeatable_keys: Collection[str],
    negatable_keys: Collection[str],
) -> tuple[str, str, bool]:
    """Classify a completion prefix and retain its unary polarity."""
    cursor = min(max(cursor, 0), len(text))
    prefix_text = text[:cursor]
    if not prefix_text or prefix_text[-1].isspace():
        return ("key", "", False)
    tokens = tokenize(prefix_text, strict=False)
    if not tokens:
        return ("key", "", False)
    token = tokens[-1]
    if token.wholly_quoted:
        return ("text", token.value, False)
    value = token.body
    quoted = token.body_quoted
    if token.negated and quoted and all(quoted):
        return ("text", value, True)
    colon = _unquoted_index(value, quoted, ":")
    if colon < 0:
        return ("key", value, token.negated)
    active_keys = negatable_keys if token.negated else keys
    key = value[:colon].casefold()
    if key not in active_keys:
        return ("key", value, token.negated)
    value = value[colon + 1 :]
    quoted = quoted[colon + 1 :]
    if key in repeatable_keys:
        comma = _last_unquoted_index(value, quoted, ",")
        if comma >= 0:
            value = value[comma + 1 :]
    return (key, value, token.negated)


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
    return _unquoted_index(token.value, token.quoted, character)


def _unquoted_index(
    value: str,
    quoted: tuple[bool, ...],
    character: str,
) -> int:
    """Return the first unquoted *character* offset in decoded text."""
    return next(
        (
            index
            for index, candidate in enumerate(value)
            if candidate == character and not quoted[index]
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
        or (not keyed and (":" in value or value.startswith("-")))
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toggle_flag_token(text: str, key: str) -> str:
    """Cycle a boolean flag through on, inverted, and off.

    Quote-aware: a wholly quoted ``"key"`` or a negated quoted ``-"key"``
    stays free text. An existing ``key`` / ``key:true`` / ``key:false`` /
    ``-key`` spelling is rewritten in place rather than appended (which the
    grammar would reject as a duplicate). Other tokens keep their original
    spelling and order; removing the last occurrence collapses the separator
    whitespace around it the same way a single-space join would.
    """
    key = key.casefold()
    match: FilterToken | None = None
    state: str | None = None
    for token in tokenize(text, strict=False):
        state = _flag_token_state(token, key)
        if state is not None:
            match = token
            break
    if match is None:
        return _append_query_token(text, key)
    if state == "on":
        return f"{text[: match.start]}-{key}{text[match.end :]}"
    return _remove_token_span(text, match.start, match.end)


def _flag_token_state(token: FilterToken, key: str) -> str | None:
    """Return ``"on"`` or ``"inverted"`` when *token* is a flag for *key*."""
    if token.wholly_quoted:
        return None
    colon = unquoted_index(token, ":")
    key_start = 1 if token.negated else 0
    if colon < 0:
        if any(token.body_quoted) or token.body.casefold() != key:
            return None
        return "inverted" if token.negated else "on"
    if token.value[key_start:colon].casefold() != key:
        return None
    value = token.value[colon + 1 :].casefold()
    is_false = value == "false"
    if is_false:
        return "on" if token.negated else "inverted"
    return "inverted" if token.negated else "on"


def _append_query_token(text: str, token: str) -> str:
    stripped = text.strip()
    if not stripped:
        return token
    return f"{stripped} {token}"


def _remove_token_span(text: str, start: int, end: int) -> str:
    """Drop ``text[start:end]`` and the separator whitespace around it."""
    while end < len(text) and text[end].isspace():
        end += 1
    if end >= len(text):
        while start > 0 and text[start - 1].isspace():
            start -= 1
    return text[:start] + text[end:]


__all__ = [
    "FilterQueryError",
    "FilterToken",
    "completion_context",
    "error_for_token",
    "quote_value",
    "split_unquoted",
    "tokenize",
    "toggle_flag_token",
    "unknown_key_error",
    "unquoted_index",
]
