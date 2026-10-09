"""Queue and hold occurrence collection for prompt directives."""

from __future__ import annotations

import re
from typing import Any

from ._directive_collect_scan import directive_matches_outside_alt
from ._directive_types import _DIRECTIVE_ALIASES
from ._parsing import find_matching_paren_for_args, parse_arg_spans
from ._parsing_args import process_text_block


def collect_queue_directive_occurrences(prompt: str) -> list[dict[str, Any]]:
    """Collect `%queue` occurrences from a fenced/disabled protected prompt."""
    occurrences: list[dict[str, Any]] = []
    for match in directive_matches_outside_alt(prompt):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name != "queue":
            continue
        occurrence, _match_end = collect_queue_occurrence(prompt, match)
        occurrences.append(occurrence)
    return occurrences


def collect_queue_occurrence(
    prompt: str,
    match: re.Match[str],
) -> tuple[dict[str, Any], int]:
    """Return a Rust queue occurrence payload for one `%queue` / `%q` match."""
    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)
    match_end = match.end()
    args: list[dict[str, str]] = []
    if has_open_paren:
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is not None:
            match_end = paren_end + 1
            args = _queue_args_from_paren_content(
                prompt[paren_start + 1 : paren_end],
            )
    elif colon_arg is not None:
        args = [{"value": _decode_queue_arg_value(colon_arg)}]

    return (
        {
            "source": prompt[match.start() : match_end],
            "source_span": [match.start(), match_end],
            "args": args,
            "has_plus_suffix": plus_suffix is not None,
        },
        match_end,
    )


def collect_hold_occurrence(
    prompt: str,
    match: re.Match[str],
) -> tuple[dict[str, Any], int]:
    """Return a Rust hold occurrence payload for one `%hold` match."""
    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)
    match_end = match.end()
    args: list[dict[str, str]] = []
    if has_open_paren:
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(prompt, paren_start)
        if paren_end is not None:
            match_end = paren_end + 1
            args = _hold_args_from_paren_content(
                prompt[paren_start + 1 : paren_end],
            )
    elif colon_arg is not None:
        args = [{"value": _decode_directive_arg_value(colon_arg)}]

    return (
        {
            "source": prompt[match.start() : match_end],
            "source_span": [match.start(), match_end],
            "args": args,
            "has_plus_suffix": plus_suffix is not None,
        },
        match_end,
    )


def _queue_args_from_paren_content(paren_content: str) -> list[dict[str, str]]:
    args: list[dict[str, str]] = []
    for span in parse_arg_spans(paren_content, preserve_empty_args=True):
        if span.name is None:
            args.append(
                {
                    "value": _decode_queue_arg_value(
                        paren_content[span.start : span.end],
                    )
                }
            )
            continue
        value = (
            ""
            if span.value_start is None or span.value_end is None
            else paren_content[span.value_start : span.value_end]
        )
        args.append(
            {
                "name": span.name,
                "value": _decode_queue_arg_value(value),
            }
        )
    return args


def _hold_args_from_paren_content(paren_content: str) -> list[dict[str, str]]:
    args: list[dict[str, str]] = []
    for span in parse_arg_spans(paren_content, preserve_empty_args=True):
        if span.name is None:
            args.append(
                {
                    "value": _decode_directive_arg_value(
                        paren_content[span.start : span.end],
                    )
                }
            )
            continue
        value = (
            ""
            if span.value_start is None or span.value_end is None
            else paren_content[span.value_start : span.value_end]
        )
        args.append(
            {
                "name": span.name,
                "value": _decode_directive_arg_value(value),
            }
        )
    return args


def _decode_queue_arg_value(value: str) -> str:
    return _decode_directive_arg_value(value)


def _decode_directive_arg_value(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        return value[1:-1]
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        return value[1:-1]
    return process_text_block(value)
