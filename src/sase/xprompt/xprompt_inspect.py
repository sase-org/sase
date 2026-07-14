"""Frontend-agnostic span inspection for xprompt prompt syntax.

This module is presentation-only. The canonical xprompt and directive grammar
lives in the Rust core; these scanners deliberately consume the same Python
lexical mirrors used by the launch path so editable and read-only frontends
render exactly the syntax that launch processing recognizes. Callers may opt
into known ``/skill`` spans as an editor affordance; slash references remain
literal pass-through text and are never part of launch processing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ._directive_types import (
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from ._disabled_regions import disabled_region_ranges
from ._fenced_blocks import fenced_block_ranges
from ._parsing import find_matching_paren_for_args
from ._parsing_references import (
    XPROMPT_REFERENCE_LEADING_CONTEXT,
    iter_xprompt_references,
)
from .segment_separators import _SEGMENT_SEPARATOR_RE

XPromptSpanKind = Literal[
    "invocation",
    "invocation_arg",
    "directive",
    "directive_arg",
    "separator",
    "skill",
]

_DIRECTIVE_RE = re.compile(_DIRECTIVE_PATTERN, re.MULTILINE)
_SKILL_REFERENCE_RE = re.compile(
    XPROMPT_REFERENCE_LEADING_CONTEXT
    + r"/(?P<name>[A-Za-z0-9_]+)(?=$|[\s'\"`?!;,()\[\]{}<>|&=+*^%$:\\])",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class XPromptSpan:
    """A highlightable xprompt span using character offsets."""

    start: int
    end: int
    kind: XPromptSpanKind


def tokenize(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
) -> list[XPromptSpan]:
    """Return recognized xprompt spans, sorted by source offset.

    Fenced code blocks and ``%xprompts_enabled:false`` regions are excluded.
    Unknown directives remain unstyled, matching launch parsing behavior.
    Slash-skill spans are emitted only for names supplied in *known_skills*.
    """
    if not text or (
        "#" not in text
        and "%" not in text
        and "---" not in text
        and (not known_skills or "/" not in text)
    ):
        return []

    protected = sorted([*fenced_block_ranges(text), *disabled_region_ranges(text)])
    spans: list[XPromptSpan] = []

    if "#" in text:
        for reference in iter_xprompt_references(text):
            if _overlaps_protected(reference.start, reference.end, protected):
                continue
            argument_start = reference.end - len(reference.argument_source)
            spans.append(XPromptSpan(reference.start, argument_start, "invocation"))
            if argument_start < reference.end:
                spans.append(
                    XPromptSpan(argument_start, reference.end, "invocation_arg")
                )

    if "%" in text:
        for match in _DIRECTIVE_RE.finditer(text):
            raw_name = match.group(1)
            name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
            if name not in _KNOWN_DIRECTIVES:
                continue
            end = _directive_end(text, match)
            if _overlaps_protected(match.start(), end, protected):
                continue
            spans.append(XPromptSpan(match.start(), match.end(1), "directive"))
            if match.end(1) < end:
                spans.append(XPromptSpan(match.end(1), end, "directive_arg"))

    if "---" in text:
        for match in _SEGMENT_SEPARATOR_RE.finditer(text):
            if not _overlaps_protected(match.start(), match.end(), protected):
                spans.append(XPromptSpan(match.start(), match.end(), "separator"))

    if known_skills and "/" in text:
        for match in _SKILL_REFERENCE_RE.finditer(text):
            if match.group("name") not in known_skills:
                continue
            if not _overlaps_protected(match.start(), match.end(), protected):
                spans.append(XPromptSpan(match.start(), match.end(), "skill"))

    spans.sort(key=lambda span: (span.start, span.end))
    return spans


def _overlaps_protected(
    start: int,
    end: int,
    protected_ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < protected_end and end > protected_start
        for protected_start, protected_end in protected_ranges
    )


def _directive_end(text: str, match: re.Match[str]) -> int:
    if match.group(2) is None:
        return match.end()
    paren_start = match.end() - 1
    paren_end = find_matching_paren_for_args(text, paren_start)
    return match.end() if paren_end is None else paren_end + 1


__all__ = ["XPromptSpan", "XPromptSpanKind", "tokenize"]
