"""Frontend-agnostic span inspection for xprompt prompt syntax.

This module is presentation-only. The canonical xprompt and directive grammar
lives in the Rust core; these scanners deliberately consume the same Python
lexical mirrors used by the launch path so editable and read-only frontends
render exactly the syntax that launch processing recognizes. Callers may opt
into known ``/skill`` spans as an editor affordance; slash references remain
literal pass-through text and are never part of launch processing.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator, Mapping
import re
from dataclasses import dataclass
from typing import Any, Literal

from ._directive_types import (
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from ._literal_zones import literal_zone_ranges
from ._parsing import find_matching_paren_for_args
from ._parsing_references import (
    XPROMPT_REFERENCE_LEADING_CONTEXT,
    XPROMPT_REFERENCE_PATTERN,
    xprompt_reference_from_match,
)
from .segment_separators import _SEGMENT_SEPARATOR_RE

XPromptSpanKind = Literal[
    "invocation",
    "invocation_arg",
    "directive",
    "directive_arg",
    "separator",
    "skill",
    "project_tag",
    "project_tag_unknown",
]

_DIRECTIVE_RE = re.compile(_DIRECTIVE_PATTERN, re.MULTILINE)
_SKILL_REFERENCE_RE = re.compile(
    XPROMPT_REFERENCE_LEADING_CONTEXT
    + r"/(?P<name>[A-Za-z0-9_]+)(?=$|[\s'\"`?!;,()\[\]{}<>|&=+*^%$:\\])",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class XPromptSpan:
    """A highlightable xprompt span using character offsets.

    ``project_tag`` spans are resolved tags and carry the project's
    accent (``None`` renders neutral, e.g. disabled projects and
    ``home``), its catalog state, and the ``name_start`` split between
    the ``+`` sigil and the name. ``project_tag_unknown`` spans are
    anchored tags that did not resolve.
    """

    start: int
    end: int
    kind: XPromptSpanKind
    accent: str | None = None
    tag_state: str | None = None
    name_start: int | None = None


def tokenize(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
) -> list[XPromptSpan]:
    """Return recognized xprompt spans, sorted by source offset.

    Fenced blocks, inline code, and ``%xprompts_enabled:false`` regions are
    excluded.
    Unknown directives remain unstyled, matching launch parsing behavior.
    Slash-skill spans are emitted only for names supplied in *known_skills*.
    """
    if not text or (
        "#" not in text
        and "%" not in text
        and "---" not in text
        and "+" not in text
        and (not known_skills or "/" not in text)
    ):
        return []

    protected = literal_zone_ranges(text)
    spans: list[XPromptSpan] = []

    if "#" in text:
        for match in _matches_outside_ranges(
            XPROMPT_REFERENCE_PATTERN,
            text,
            protected,
            needle="#",
        ):
            reference = xprompt_reference_from_match(text, match)
            if _overlaps_protected(reference.start, reference.end, protected):
                continue
            argument_start = reference.end - len(reference.argument_source)
            spans.append(XPromptSpan(reference.start, argument_start, "invocation"))
            if argument_start < reference.end:
                spans.append(
                    XPromptSpan(argument_start, reference.end, "invocation_arg")
                )

    if "%" in text:
        for match in _matches_outside_ranges(
            _DIRECTIVE_RE,
            text,
            protected,
            needle="%",
        ):
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
        for match in _matches_outside_ranges(
            _SEGMENT_SEPARATOR_RE,
            text,
            protected,
            needle="---",
        ):
            spans.append(XPromptSpan(match.start(), match.end(), "separator"))

    if known_skills and "/" in text:
        for match in _matches_outside_ranges(
            _SKILL_REFERENCE_RE,
            text,
            protected,
            needle="/",
        ):
            if match.group("name") not in known_skills:
                continue
            spans.append(XPromptSpan(match.start(), match.end(), "skill"))

    if "+" in text:
        spans.extend(_project_tag_spans(text, protected))

    spans.sort(key=lambda span: (span.start, span.end))
    return spans


def _project_tag_spans(
    text: str,
    protected: list[tuple[int, int]],
) -> list[XPromptSpan]:
    """Return resolved-tag and anchored-unknown-tag spans (D5/D6).

    Uses the core expansion report against the warm catalog snapshot, so
    only tags that launch would resolve are styled. Unanchored unknown
    tags are plain text. Fails open to no spans when the catalog is cold
    or the binding is unavailable; the next highlight rebuild after
    warm-up picks tags up.
    """
    if "+" not in text:
        return []
    try:
        from sase.project_tags.catalog import peek_project_tag_catalog

        catalog = peek_project_tag_catalog()
    except Exception:
        return []
    if catalog is None:
        return []
    try:
        targets = catalog.targets
        if not targets:
            return []
        from sase.core.rust import require_rust_binding

        report = require_rust_binding("project_tag_expand")(
            text, catalog.wire_targets()
        )
    except Exception:
        return []
    if not isinstance(report, Mapping):
        return []
    raw_tags = report.get("tags")
    if not isinstance(raw_tags, list):
        return []
    spans: list[XPromptSpan] = []
    for raw_tag in raw_tags:
        span = _project_tag_span(raw_tag, text, catalog, protected)
        if span is not None:
            spans.append(span)
    return spans


def _project_tag_span(
    raw_tag: object,
    text: str,
    catalog: Any,
    protected: list[tuple[int, int]],
) -> XPromptSpan | None:
    """Convert one core expansion tag to a span, or ``None`` to skip."""
    if not isinstance(raw_tag, Mapping):
        return None
    start = raw_tag.get("start")
    end = raw_tag.get("end")
    name_start = raw_tag.get("name_start")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(name_start, int)
        or isinstance(name_start, bool)
    ):
        return None
    if not 0 <= start < name_start < end <= len(text):
        return None
    if _overlaps_protected(start, end, protected):
        return None
    resolution = raw_tag.get("resolution")
    kind = resolution.get("kind") if isinstance(resolution, Mapping) else None
    anchored = raw_tag.get("anchored") is True
    if kind == "resolved":
        index = (
            resolution.get("target_index") if isinstance(resolution, Mapping) else None
        )
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        try:
            target = catalog.target(index)
        except Exception:
            return None
        accent = getattr(target, "accent", None)
        state = getattr(target, "state", None)
        return XPromptSpan(
            start,
            end,
            "project_tag",
            accent=accent if isinstance(accent, str) else None,
            tag_state=state if isinstance(state, str) else None,
            name_start=name_start,
        )
    if not anchored:
        return None
    return XPromptSpan(start, end, "project_tag_unknown", name_start=name_start)


def _directive_end(text: str, match: re.Match[str]) -> int:
    if match.group(2) is None:
        return match.end()
    paren_start = match.end() - 1
    paren_end = find_matching_paren_for_args(text, paren_start)
    return match.end() if paren_end is None else paren_end + 1


def _overlaps_protected(
    start: int,
    end: int,
    protected_ranges: list[tuple[int, int]],
) -> bool:
    candidate = bisect_left(protected_ranges, (end,)) - 1
    return candidate >= 0 and protected_ranges[candidate][1] > start


def _matches_outside_ranges(
    pattern: re.Pattern[str],
    text: str,
    ranges: list[tuple[int, int]],
    *,
    needle: str,
) -> Iterator[re.Match[str]]:
    cursor = 0
    for start, end in ranges:
        if cursor < start and text.find(needle, cursor, start) != -1:
            yield from pattern.finditer(text, cursor, start)
        cursor = max(cursor, end)
    if cursor < len(text) and text.find(needle, cursor) != -1:
        yield from pattern.finditer(text, cursor)


__all__ = ["XPromptSpan", "XPromptSpanKind", "tokenize"]
