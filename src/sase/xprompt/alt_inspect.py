"""Frontend-agnostic inspection helpers for ``%{...}`` alt-shorthand prompts.

These helpers compute span information used to *highlight* the ``%{A | B}``
fan-out shorthand in prompt editors. They are presentation-layer only: the
canonical fan-out grammar lives in the Rust core
(``sase_core::agent_launch``). The scanning rules here intentionally mirror
that grammar so the visual treatment matches launch behavior:

- ``%{`` is only recognized at a directive-valid position (start of line, or
  after whitespace / an opening bracket / a quote / a directive-value colon);
- the matching ``}`` is found by counting only ``{``/``}`` pairs and ignoring
  backtick-quoted spans;
- top-level ``|`` separators split branches, where "top-level" means outside
  ``()``/``[]``/``{}`` nesting and backtick spans;
- an optional ``name=`` prefix on a branch names that branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ._fenced_blocks import fenced_block_ranges

AltSpanKind = Literal["delimiter", "separator", "branch_name", "error"]

# ``%{`` at a directive-valid position. Mirrors the brace arm of the Rust
# ``alt_directive_re`` so detection matches launch fan-out exactly. Group 2 is
# the ``%{`` marker; the preceding character is consumed (not a lookbehind) to
# match the non-overlapping behavior of the Rust scanner.
_ALT_OPEN_RE = re.compile(r"(?m)(^|[\s(\[{\"':])(%\{)")


@dataclass(frozen=True, slots=True)
class AltSpan:
    """A single highlightable span of ``%{...}`` syntax.

    Offsets are character offsets into the original (unmasked) text.
    """

    start: int
    end: int
    kind: AltSpanKind


def tokenize(text: str) -> list[AltSpan]:
    """Return ``%{...}`` alt-shorthand spans, sorted by start offset.

    Spans inside fenced code blocks are ignored, matching the Jinja overlay.
    An unmatched ``%{`` opener yields a single ``error`` span over ``%{``.
    """
    if "%{" not in text:
        return []

    masked = _mask_fenced_blocks(text)
    spans: list[AltSpan] = []
    for match in _ALT_OPEN_RE.finditer(masked):
        marker = match.start(2)
        open_brace = match.end(2) - 1
        close = _find_matching_brace(masked, open_brace)
        if close is None:
            spans.append(AltSpan(marker, open_brace + 1, "error"))
            continue
        spans.append(AltSpan(marker, open_brace + 1, "delimiter"))
        spans.append(AltSpan(close, close + 1, "delimiter"))
        inner_start = open_brace + 1
        spans.extend(_branch_spans(masked[inner_start:close], inner_start))

    spans.sort(key=lambda span: span.start)
    return spans


def _find_matching_brace(text: str, open_start: int) -> int | None:
    """Return the index of the ``}`` closing the ``{`` at ``open_start``.

    Counts only ``{``/``}`` pairs and ignores backtick-quoted spans, matching
    the Rust ``find_matching_delimiter`` for the brace delimiter.
    """
    depth = 0
    in_backticks = False
    for idx in range(open_start, len(text)):
        ch = text[idx]
        if ch == "`":
            in_backticks = not in_backticks
            continue
        if in_backticks:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _branch_spans(inner: str, base: int) -> list[AltSpan]:
    """Spans for top-level ``|`` separators and ``name=`` branch prefixes.

    ``inner`` is the text between ``%{`` and ``}``; ``base`` is its offset in
    the original text. Separator/depth handling mirrors the Rust
    ``parse_directive_args_with_names`` for the ``|`` separator.
    """
    spans: list[AltSpan] = []
    branch_start = 0
    depth = 0
    in_backticks = False
    for idx, ch in enumerate(inner):
        if ch == "`":
            in_backticks = not in_backticks
            continue
        if in_backticks:
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth > 0:
                depth -= 1
        elif ch == "|" and depth == 0:
            spans.append(AltSpan(base + idx, base + idx + 1, "separator"))
            spans.extend(
                _branch_name_span(inner[branch_start:idx], base + branch_start)
            )
            branch_start = idx + 1
    spans.extend(_branch_name_span(inner[branch_start:], base + branch_start))
    return spans


def _branch_name_span(branch: str, base: int) -> list[AltSpan]:
    """Span for a ``name=`` prefix on a single branch, if present.

    The name is the text before the first top-level ``=``; it must be
    non-empty after trimming. Mirrors the Rust ``split_named_directive_arg``.
    """
    depth = 0
    in_backticks = False
    for idx, ch in enumerate(branch):
        if ch == "`":
            in_backticks = not in_backticks
            continue
        if in_backticks:
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth > 0:
                depth -= 1
        elif ch == "=" and depth == 0:
            name = branch[:idx]
            stripped = name.strip()
            if not stripped:
                return []
            lead = len(name) - len(name.lstrip())
            name_start = base + lead
            return [AltSpan(name_start, name_start + len(stripped), "branch_name")]
    return []


def _mask_fenced_blocks(text: str) -> str:
    """Blank out fenced code blocks while preserving offsets and newlines."""
    ranges = fenced_block_ranges(text)
    if not ranges:
        return text
    chars = list(text)
    for start, end in ranges:
        for idx in range(start, end):
            if chars[idx] not in "\r\n":
                chars[idx] = " "
    return "".join(chars)
