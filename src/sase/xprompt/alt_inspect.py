"""Frontend-agnostic inspection helpers for alt fan-out prompts.

These helpers compute span information used to highlight ``%{A | B}``,
``%alt(A, B)``, and ``%(A, B)`` fan-out forms in prompt editors. They are
presentation-layer only: the canonical fan-out grammar lives in the Rust core
(``sase_core::agent_launch``). The scanning rules here intentionally mirror
that grammar so the visual treatment matches launch behavior:

- an opener is only recognized at a directive-valid position (start of line, or
  after whitespace / an opening bracket / a quote / a directive-value colon);
- matching delimiters respect nested delimiters and quoted/text-block spans;
- top-level ``|`` (brace form) or ``,`` (paren forms) separators split branches,
  where "top-level" means outside
  ``()``/``[]``/``{}`` nesting and backtick spans;
- an optional ``name=`` prefix on a branch names that branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._literal_zones import literal_zone_ranges
from ._parsing import find_matching_paren_for_args, find_text_block_close_for_args

AltSpanKind = Literal["delimiter", "separator", "branch_name", "error"]


@dataclass(frozen=True, slots=True)
class AltSpan:
    """A single highlightable span of alt fan-out syntax.

    Offsets are character offsets into the original (unmasked) text.
    """

    start: int
    end: int
    kind: AltSpanKind


def tokenize(text: str) -> list[AltSpan]:
    """Return alt fan-out spans, sorted by start offset.

    Spans inside fenced blocks, inline code, or disabled regions are ignored.
    An unmatched opener yields a single ``error`` span over the opener.
    """
    if "%" not in text:
        return []

    masked = _mask_protected_regions(text)
    spans: list[AltSpan] = []
    for match in _ALT_DIRECTIVE_RE.finditer(masked):
        marker = match.start(1)
        open_delimiter = match.end(1) - 1
        brace_form = masked[open_delimiter] == "{"
        close = (
            _find_matching_brace(masked, open_delimiter)
            if brace_form
            else find_matching_paren_for_args(masked, open_delimiter)
        )
        if close is None:
            spans.append(AltSpan(marker, open_delimiter + 1, "error"))
            continue
        spans.append(AltSpan(marker, open_delimiter + 1, "delimiter"))
        spans.append(AltSpan(close, close + 1, "delimiter"))
        inner_start = open_delimiter + 1
        spans.extend(
            _branch_spans(
                masked[inner_start:close],
                inner_start,
                separator="|" if brace_form else ",",
            )
        )

    spans.sort(key=lambda span: span.start)
    return spans


def _find_matching_brace(text: str, open_start: int) -> int | None:
    """Return the matching brace while ignoring backtick-quoted spans."""
    depth = 0
    in_backticks = False
    for idx in range(open_start, len(text)):
        char = text[idx]
        if char == "`":
            in_backticks = not in_backticks
            continue
        if in_backticks:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _branch_spans(inner: str, base: int, *, separator: str) -> list[AltSpan]:
    """Spans for top-level ``|`` separators and ``name=`` branch prefixes.

    ``inner`` is the text between ``%{`` and ``}``; ``base`` is its offset in
    the original text. Separator/depth handling mirrors the Rust
    ``parse_directive_args_with_names`` for the selected separator.
    """
    spans: list[AltSpan] = []
    branch_start = 0
    for idx in _top_level_offsets(inner, separator):
        spans.append(AltSpan(base + idx, base + idx + 1, "separator"))
        spans.extend(_branch_name_span(inner[branch_start:idx], base + branch_start))
        branch_start = idx + 1
    spans.extend(_branch_name_span(inner[branch_start:], base + branch_start))
    return spans


def _branch_name_span(branch: str, base: int) -> list[AltSpan]:
    """Span for a ``name=`` prefix on a single branch, if present.

    The name is the text before the first top-level ``=``; it must be
    non-empty after trimming. Mirrors the Rust ``split_named_directive_arg``.
    """
    offsets = _top_level_offsets(branch, "=")
    if offsets:
        name = branch[: offsets[0]]
        stripped = name.strip()
        if not stripped:
            return []
        lead = len(name) - len(name.lstrip())
        name_start = base + lead
        return [AltSpan(name_start, name_start + len(stripped), "branch_name")]
    return []


def _top_level_offsets(text: str, target: str) -> list[int]:
    """Return target offsets outside nesting, quotes, and text blocks."""
    offsets: list[int] = []
    depth = 0
    quote: str | None = None
    escaped = False
    idx = 0
    while idx < len(text):
        if quote is None and text[idx : idx + 2] == "[[":
            close = find_text_block_close_for_args(text, idx)
            if close is None:
                break
            idx = close + 2
            continue

        char = text[idx]
        if escaped:
            escaped = False
        elif quote is not None:
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"', "`"}:
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth > 0:
                depth -= 1
        elif char == target and depth == 0:
            offsets.append(idx)
        idx += 1
    return offsets


def _mask_protected_regions(text: str) -> str:
    """Blank protected regions while preserving offsets and newlines."""
    ranges = literal_zone_ranges(text)
    if not ranges:
        return text
    chars = list(text)
    for start, end in ranges:
        for idx in range(start, end):
            if chars[idx] not in "\r\n":
                chars[idx] = " "
    return "".join(chars)
