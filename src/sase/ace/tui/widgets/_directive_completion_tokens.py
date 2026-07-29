"""Token extraction helpers for prompt directive completion."""

from __future__ import annotations

import re
from collections.abc import Callable

from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _KNOWN_DIRECTIVES

_DIRECTIVE_TOKEN_RE = re.compile(r"^%[A-Za-z0-9_]*$")
_DIRECTIVE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_]")
_DIRECTIVE_OPENING_CONTEXTS = frozenset("([{\"'")


def is_directive_like_token(token: str) -> bool:
    """Return True when token looks like a prompt directive reference."""
    return _DIRECTIVE_TOKEN_RE.fullmatch(token) is not None


def extract_directive_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str] | None:
    """Extract a directive token around a cursor position in one line."""
    col = min(col, len(line))

    token_start = col
    while token_start > 0 and _is_directive_identifier(line[token_start - 1]):
        token_start -= 1

    percent_index = token_start - 1
    if percent_index < 0 or line[percent_index] != "%":
        return None
    if not _has_valid_directive_context(line, percent_index):
        return None

    token_end = col
    while token_end < len(line) and _is_directive_identifier(line[token_end]):
        token_end += 1

    token = line[percent_index:token_end]
    if not is_directive_like_token(token):
        return None
    return percent_index, token_end, token


def extract_directive_arg_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str, str] | None:
    """Extract a fixed-value directive argument token around the cursor.

    Returns ``(arg_start, arg_end, directive_name, partial)`` where
    ``directive_name`` is canonical and ``arg_start``/``arg_end`` bound the
    replaceable argument value after ``:``.
    """
    col = min(col, len(line))

    percent_index = line.rfind("%", 0, col)
    if percent_index < 0:
        return None
    if not _has_valid_directive_context(line, percent_index):
        return None

    name_start = percent_index + 1
    name_end = name_start
    while name_end < len(line) and _is_directive_identifier(line[name_end]):
        name_end += 1
    if name_end == name_start or name_end >= len(line):
        return None

    raw_name = line[name_start:name_end]
    marker = line[name_end]
    if marker not in {":", "("}:
        return None
    if col <= name_end:
        return None

    directive_name = canonical_directive_name(raw_name)
    if directive_name is None:
        return None

    if marker == "(":
        if directive_name == "clan":
            return _extract_clan_paren_arg_token(line, col, name_end)
        if directive_name == "id":
            return _extract_id_paren_arg_token(line, col, name_end)
        if directive_name == "wait":
            return _extract_wait_paren_arg_token(line, col, name_end)
        if directive_name == "model":
            return _extract_model_paren_arg_token(line, col, name_end)
        return None

    colon_index = name_end
    if col <= colon_index:
        return None
    if directive_name == "wait":
        return _extract_wait_colon_arg_token(line, col, colon_index)

    arg_start = colon_index + 1
    arg_predicate = _directive_argument_predicate(directive_name)
    if any(not arg_predicate(char) for char in line[arg_start:col]):
        return None

    arg_end = col
    while arg_end < len(line) and arg_predicate(line[arg_end]):
        arg_end += 1

    if directive_name == "model":
        prefix = line[arg_start:col]
        at_index = prefix.rfind("@")
        # A leading `@` marks a model alias. Only a non-leading `@` opens
        # reasoning-effort completion for a `%model:<model>@<effort>` suffix.
        if at_index > 0:
            suffix_start = arg_start + at_index + 1
            suffix_end = col
            while suffix_end < len(line) and _is_directive_argument_identifier(
                line[suffix_end]
            ):
                suffix_end += 1
            return suffix_start, suffix_end, "effort", line[suffix_start:suffix_end]

    return arg_start, arg_end, directive_name, line[arg_start:arg_end]


def selected_wait_values_around_cursor(
    line: str,
    active_start: int,
) -> frozenset[str]:
    """Return completed ``%wait`` values outside the active comma clause."""
    percent_index = line.rfind("%", 0, active_start)
    if percent_index < 0:
        return frozenset()
    name_end = percent_index + 1
    while name_end < len(line) and _is_directive_identifier(line[name_end]):
        name_end += 1
    if name_end >= len(line) or line[name_end] not in {":", "("}:
        return frozenset()

    value_start = name_end + 1
    body_end = len(line)
    if line[name_end] == "(":
        close_index = line.find(")", value_start)
        if close_index >= 0:
            body_end = close_index
    active_index = line.count(",", value_start, active_start)
    selected: set[str] = set()
    for index, raw_value in enumerate(line[value_start:body_end].split(",")):
        if index == active_index:
            continue
        value = raw_value.strip()
        if value and all(
            _is_wait_directive_argument_identifier(char) for char in value
        ):
            selected.add(value)
    return frozenset(selected)


def canonical_directive_name(raw_name: str) -> str | None:
    """Resolve a directive alias to a known canonical name."""
    canonical = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
    if canonical not in _KNOWN_DIRECTIVES:
        return None
    return canonical


def _extract_wait_colon_arg_token(
    line: str,
    col: int,
    colon_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = colon_index + 1
    if not _is_valid_wait_argument_prefix(line[value_start:col]):
        return None
    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1

    if any(
        not _is_wait_directive_argument_identifier(char)
        for char in line[fragment_start:col]
    ):
        return None

    fragment_end = col
    while fragment_end < len(line) and _is_wait_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1

    return fragment_start, fragment_end, "wait", line[fragment_start:fragment_end]


def _extract_wait_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    if ")" in line[value_start:col]:
        return None
    if not _is_valid_wait_argument_prefix(line[value_start:col]):
        return None

    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1

    if any(
        not _is_wait_directive_argument_identifier(char)
        for char in line[fragment_start:col]
    ):
        return None

    fragment_end = col
    while fragment_end < len(line) and _is_wait_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1

    return fragment_start, fragment_end, "wait", line[fragment_start:fragment_end]


def _extract_clan_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    prefix = line[value_start:col]
    if ")" in prefix:
        return None
    comma_index = line.rfind(",", value_start, col)
    if comma_index < value_start:
        return None
    fragment_start = comma_index + 1
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1
    fragment = line[fragment_start:col]
    if "=" in fragment or any(
        not _is_directive_argument_identifier(char) for char in fragment
    ):
        return None
    fragment_end = col
    while fragment_end < len(line) and _is_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1
    return (
        fragment_start,
        fragment_end,
        "clan_keyword",
        line[fragment_start:fragment_end],
    )


def _extract_id_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    """Extract an ``%id(...)`` keyword fragment in any argument slot."""
    value_start = open_index + 1
    prefix = line[value_start:col]
    if ")" in prefix:
        return None
    comma_index = line.rfind(",", value_start, col)
    fragment_start = comma_index + 1 if comma_index >= value_start else value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1
    fragment = line[fragment_start:col]
    if "=" in fragment or any(
        not _is_directive_argument_identifier(char) for char in fragment
    ):
        return None
    fragment_end = col
    while fragment_end < len(line) and _is_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1
    return (
        fragment_start,
        fragment_end,
        "id_keyword",
        line[fragment_start:fragment_end],
    )


def _extract_model_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    prefix = line[value_start:col]
    if ")" in prefix:
        return None

    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1
    fragment = line[fragment_start:col]

    equals_index = fragment.find("=")
    if equals_index >= 0:
        arg_start = fragment_start + equals_index + 1
        if any(
            not _is_model_directive_argument_identifier(char)
            for char in line[arg_start:col]
        ):
            return None
        arg_end = col
        while arg_end < len(line) and _is_model_directive_argument_identifier(
            line[arg_end]
        ):
            arg_end += 1
        return arg_start, arg_end, "model", line[arg_start:arg_end]

    if any(not _is_model_directive_argument_identifier(char) for char in fragment):
        return None
    arg_end = col
    while arg_end < len(line) and _is_model_directive_argument_identifier(
        line[arg_end]
    ):
        arg_end += 1

    if fragment_start == value_start:
        at_index = fragment.rfind("@")
        if at_index > 0:
            effort_start = fragment_start + at_index + 1
            return effort_start, arg_end, "effort", line[effort_start:arg_end]
        return (
            fragment_start,
            arg_end,
            "model_or_alias_key",
            line[fragment_start:arg_end],
        )
    return fragment_start, arg_end, "model_alias_key", line[fragment_start:arg_end]


def _has_valid_directive_context(line: str, percent_index: int) -> bool:
    if percent_index == 0:
        return True
    previous = line[percent_index - 1]
    return previous.isspace() or previous in _DIRECTIVE_OPENING_CONTEXTS


def _is_directive_identifier(char: str) -> bool:
    return _DIRECTIVE_IDENTIFIER_RE.fullmatch(char) is not None


def _is_directive_argument_identifier(char: str) -> bool:
    return _is_directive_identifier(char) or char in "-="


def _is_model_directive_argument_identifier(char: str) -> bool:
    return _is_directive_argument_identifier(char) or char in "./@"


def _is_wait_directive_argument_identifier(char: str) -> bool:
    return _is_directive_identifier(char) or char in "-.=@"


def _is_valid_wait_argument_prefix(prefix: str) -> bool:
    """Return True when prefix is a well-formed (possibly partial) wait list.

    Each comma-separated segment may carry surrounding whitespace but must
    otherwise contain only wait-argument identifier characters. Prose with
    internal spaces before the active fragment is therefore rejected, so a
    later prose comma cannot masquerade as a new comma-separated wait argument.
    """
    for segment in prefix.split(","):
        if any(
            not _is_wait_directive_argument_identifier(char) for char in segment.strip()
        ):
            return False
    return True


def _directive_argument_predicate(directive_name: str) -> Callable[[str], bool]:
    if directive_name == "model":
        return _is_model_directive_argument_identifier
    return _is_directive_argument_identifier
