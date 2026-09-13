"""Read-only diagnostics for retired prompt directive syntax."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._directive_types import (
    _DEPRECATED_DIRECTIVE_MESSAGES,
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
)
from ._disabled_regions import protect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
)


@dataclass(frozen=True, slots=True)
class RetiredDirectiveUsage:
    """One retired directive syntax occurrence in an xprompt definition."""

    line: int
    source: str
    message: str


def retired_wait_keyword_message(named_args: Mapping[str, str]) -> str | None:
    """Return the migration message for retired ``%wait`` queue keywords."""
    if "runners" in named_args:
        return (
            "%wait(runners=...) has moved to %queue. "
            "Use %queue(capacity=N) or %q:N, and keep dependencies on %wait."
        )
    if "capacity" in named_args:
        return (
            "%wait(capacity=...) belongs on %queue. "
            "Use %queue(capacity=N) or %q:N, and keep dependencies on %wait."
        )
    if "priority" in named_args:
        return (
            "%wait(priority=...) has moved to %queue. "
            "Use %queue(priority=N) or %q(p=N), and keep dependencies on %wait."
        )
    if "p" in named_args:
        return "%wait(p=...) is unsupported. Use %queue(priority=...) or %q(p=...)."
    return None


def find_retired_directive_usages(content: str) -> list[RetiredDirectiveUsage]:
    """Return retired directive syntax diagnostics for one definition body.

    The scan is intentionally read-only and best-effort. It protects the same
    literal regions the launch parser ignores and returns no diagnostics rather
    than raising when malformed or templated syntax cannot be parsed safely.
    """
    if "%" not in content:
        return []

    try:
        protected = _protect_literal_regions_preserving_lines(content)
        ignored_regions = [
            *_alt_inner_regions(protected),
            *_code_directive_inner_ranges(protected),
        ]
        usages: list[RetiredDirectiveUsage] = []
        for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
            if _offset_is_ignored(match.start(), ignored_regions):
                continue
            raw_name = match.group(1)
            name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
            if name in _DEPRECATED_DIRECTIVES:
                usages.append(
                    RetiredDirectiveUsage(
                        line=_line_for_offset(protected, match.start()),
                        source=_directive_source(protected, match),
                        message=_DEPRECATED_DIRECTIVE_MESSAGES[name],
                    )
                )
                continue
            if name != "wait" or match.group(2) is None:
                continue
            usage = _retired_wait_usage(protected, match)
            if usage is not None:
                usages.append(usage)
    except Exception:  # noqa: BLE001 - diagnostics must never break doctor.
        return []
    return usages


def _protect_literal_regions_preserving_lines(content: str) -> str:
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(content, fenced_blocks)
    protected = _replace_placeholders_with_newlines(protected, "XPF", fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    return _replace_placeholders_with_newlines(protected, "XPD", disabled_regions)


def _replace_placeholders_with_newlines(
    text: str,
    marker: str,
    values: list[str],
) -> str:
    for index, value in enumerate(values):
        text = text.replace(f"\x00{marker}_{index}\x00", "\n" * value.count("\n"))
    return text


def _retired_wait_usage(
    protected: str,
    match: re.Match[str],
) -> RetiredDirectiveUsage | None:
    paren_start = match.end() - 1
    paren_end = find_matching_paren_for_args(protected, paren_start)
    if paren_end is None:
        return None
    paren_content = protected[paren_start + 1 : paren_end]
    try:
        _, named_args = parse_args(
            paren_content,
            reject_duplicate_named_args=True,
        )
    except ValueError:
        return None
    message = retired_wait_keyword_message(named_args)
    if message is None:
        return None
    return RetiredDirectiveUsage(
        line=_line_for_offset(protected, match.start()),
        source=protected[match.start() : paren_end + 1],
        message=message,
    )


def _directive_source(protected: str, match: re.Match[str]) -> str:
    if match.group(2) is not None:
        paren_end = find_matching_paren_for_args(protected, match.end() - 1)
        if paren_end is not None:
            return protected[match.start() : paren_end + 1]
    return protected[match.start() : match.end()]


def _alt_inner_regions(protected: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(protected):
        open_pos = alt_match.end() - 1
        if protected[open_pos] == "{":
            close_pos = find_matching_brace_for_args(protected, open_pos)
        else:
            close_pos = find_matching_paren_for_args(protected, open_pos)
        if close_pos is not None:
            regions.append((open_pos + 1, close_pos))
    return regions


def _code_directive_inner_ranges(protected: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in {"if", "proc"} or match.group(2) is None:
            continue
        paren_end = find_matching_paren_for_args(protected, match.end() - 1)
        if paren_end is not None:
            ranges.append((match.end(), paren_end))
    return ranges


def _offset_is_ignored(offset: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


__all__ = [
    "RetiredDirectiveUsage",
    "find_retired_directive_usages",
    "retired_wait_keyword_message",
]
