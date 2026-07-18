"""Pure text helpers for rewriting launch-property xprompt directives."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
)
from ._disabled_regions import protect_disabled_regions, unprotect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from ._parsing import find_matching_brace_for_args, find_matching_paren_for_args

AutoMode = Literal["plan", "tale", "epic"]


@dataclass(frozen=True)
class PromptWaitDirective:
    """Canonical wait directive payload used by prompt rewrite callers."""

    agents: tuple[str, ...] = ()
    time_token: str | None = None
    runners: int | None = None

    def __bool__(self) -> bool:
        return bool(self.agents or self.time_token or self.runners is not None)


_TIME_XPROMPT_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#t(?:(\()|:(`[^`]*`|\$\([^)]*\)|[a-zA-Z0-9_.~,+/-]*[a-zA-Z0-9_~+/-]))"
)


def set_prompt_name(prompt: str, name: str) -> str:
    """Return *prompt* with a canonical ``%name:<name>`` directive."""
    return _set_prompt_directive(prompt, {"name"}, f"%name:{name}")


def set_prompt_tribe(prompt: str, tribe: str | None) -> str:
    """Return *prompt* with ``%tribe`` set or removed."""
    replacement = f"%tribe:{tribe}" if tribe else None
    # Editing an existing agent also migrates launch prompts written before
    # tribes replaced groups. These spellings remain unsupported by the
    # runtime parser; recognizing them here is cleanup, not a legacy alias.
    return _set_prompt_directive(prompt, {"g", "group", "tribe"}, replacement)


def set_prompt_auto_mode(prompt: str, mode: AutoMode | None) -> str:
    """Return *prompt* with the requested canonical ``%auto`` directive."""
    replacement = None
    if mode == "plan":
        replacement = "%auto"
    elif mode is not None:
        replacement = f"%auto:{mode}"
    return _set_prompt_directive(prompt, {"auto"}, replacement)


def set_prompt_wait(
    prompt: str,
    wait_spec: PromptWaitDirective | None,
) -> str:
    """Return *prompt* with a canonical ``%wait(...)`` directive or none."""
    replacement = _format_wait_directive(wait_spec) if wait_spec else None
    return _set_prompt_directive(
        prompt,
        {"wait"},
        replacement,
        remove_deprecated=True,
        remove_time_xprompts=True,
    )


def _format_wait_directive(wait_spec: PromptWaitDirective | None) -> str | None:
    if not wait_spec:
        return None
    parts = [_format_wait_arg(agent) for agent in wait_spec.agents]
    if wait_spec.time_token:
        parts.append(f"time={wait_spec.time_token}")
    if wait_spec.runners is not None:
        parts.append(f"runners={wait_spec.runners}")
    return f"%wait({', '.join(parts)})"


def _format_wait_arg(value: str) -> str:
    if value and not any(ch.isspace() or ch in ",()=" for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _set_prompt_directive(
    prompt: str,
    directive_names: set[str],
    replacement: str | None,
    *,
    remove_deprecated: bool = False,
    remove_time_xprompts: bool = False,
) -> str:
    protected, restore = _protect_ignored_regions(prompt)
    protected = _rewrite_protected_prompt(
        protected,
        directive_names,
        replacement,
        remove_deprecated=remove_deprecated,
        remove_time_xprompts=remove_time_xprompts,
    )
    return restore(protected)


def _protect_ignored_regions(prompt: str) -> tuple[str, Callable[[str], str]]:
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    def restore(text: str) -> str:
        text = unprotect_disabled_regions(text, disabled_regions)
        return unprotect_fenced_blocks(text, fenced_blocks)

    return protected, restore


def _rewrite_protected_prompt(
    prompt: str,
    directive_names: set[str],
    replacement: str | None,
    *,
    remove_deprecated: bool,
    remove_time_xprompts: bool,
) -> str:
    spans = list(
        _directive_spans(
            prompt,
            directive_names,
            remove_deprecated=remove_deprecated,
        )
    )
    if remove_time_xprompts:
        spans.extend(_time_xprompt_spans(prompt))
    spans = _merge_spans(spans)

    cleaned = _remove_spans(prompt, spans) if spans else prompt
    if replacement is None:
        return cleaned
    return _insert_directive(cleaned, replacement)


def _directive_spans(
    prompt: str,
    directive_names: set[str],
    *,
    remove_deprecated: bool,
) -> Iterable[tuple[int, int]]:
    alt_inner_regions = _alt_inner_regions(prompt)
    for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE):
        if _inside_regions(match.start(), alt_inner_regions):
            continue
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in directive_names and not (
            remove_deprecated and name in _DEPRECATED_DIRECTIVES
        ):
            continue
        match_end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        yield match.start(), match_end


def _time_xprompt_spans(prompt: str) -> Iterable[tuple[int, int]]:
    alt_inner_regions = _alt_inner_regions(prompt)
    for match in _TIME_XPROMPT_RE.finditer(prompt):
        if _inside_regions(match.start(), alt_inner_regions):
            continue
        match_end = match.end()
        if match.group(1) is not None:
            paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
            if paren_end is not None:
                match_end = paren_end + 1
        yield match.start(), match_end


def _alt_inner_regions(prompt: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_pos = alt_match.end() - 1
        if prompt[open_pos] == "{":
            close_pos = find_matching_brace_for_args(prompt, open_pos)
        else:
            close_pos = find_matching_paren_for_args(prompt, open_pos)
        if close_pos is None:
            continue
        regions.append((open_pos + 1, close_pos))
    return regions


def _inside_regions(pos: int, regions: Iterable[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in regions)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    removal_ranges = _line_or_span_removal_ranges(text, spans)
    parts: list[str] = []
    cursor = 0
    for start, end in removal_ranges:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _line_or_span_removal_ranges(
    text: str,
    spans: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    line_start = 0
    span_index = 0
    while line_start < len(text):
        newline_index = text.find("\n", line_start)
        line_end = len(text) if newline_index == -1 else newline_index + 1
        line_spans: list[tuple[int, int]] = []
        while span_index < len(spans) and spans[span_index][1] <= line_start:
            span_index += 1
        lookahead = span_index
        while lookahead < len(spans) and spans[lookahead][0] < line_end:
            start, end = spans[lookahead]
            line_spans.append((max(start, line_start), min(end, line_end)))
            lookahead += 1
        if not line_spans:
            line_start = line_end
            continue
        if _line_without_spans(text, line_start, line_end, line_spans).strip() == "":
            ranges.append((line_start, line_end))
        else:
            ranges.extend(
                _expand_inline_removal_span(text, line_end, start, end)
                for start, end in line_spans
            )
        line_start = line_end
    if line_start == len(text):
        return _merge_spans(ranges)
    return _merge_spans(ranges)


def _expand_inline_removal_span(
    text: str,
    line_end: int,
    start: int,
    end: int,
) -> tuple[int, int]:
    """Include separator whitespace after removed inline directives."""
    content_end = (
        line_end - 1 if line_end > 0 and text[line_end - 1] == "\n" else line_end
    )
    while end < content_end and text[end] in " \t":
        end += 1
    return start, end


def _line_without_spans(
    text: str,
    line_start: int,
    line_end: int,
    line_spans: list[tuple[int, int]],
) -> str:
    parts: list[str] = []
    cursor = line_start
    for start, end in line_spans:
        parts.append(text[cursor:start])
        cursor = end
    parts.append(text[cursor:line_end])
    return "".join(parts)


def _insert_directive(prompt: str, directive: str) -> str:
    insert_at = _frontmatter_end(prompt)
    prefix = prompt[:insert_at]
    suffix = prompt[insert_at:]
    return f"{prefix}{directive}\n{suffix}"


def _frontmatter_end(prompt: str) -> int:
    if not prompt.startswith("---\n"):
        return 0
    cursor = 4
    while cursor < len(prompt):
        next_newline = prompt.find("\n", cursor)
        line_end = len(prompt) if next_newline == -1 else next_newline + 1
        line = prompt[cursor:line_end].strip()
        if line == "---":
            return line_end
        cursor = line_end
    return 0
