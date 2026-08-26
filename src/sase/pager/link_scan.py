"""Scan plain text for typed refs, URLs, paths, and origin-scoped bare tokens.

Runs the four precedence rules from the link-traversing-pager epic's design
(``plan:202608/link_traversing_pager.md``, section D3) over one section's
plain text: typed artifact refs win over URLs, which win over file paths,
which win over origin-scoped bare tokens. No I/O: a span's presence and kind
derive from the text alone, never from resolving the reference it names.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
    HTTP_URL_PATTERN,
    file_hint_match_span,
    iter_file_path_matches,
    matches_outside_artifact_refs,
)
from sase.ace.tui.widgets.prompt_panel._hint_caps import (
    HintContentBudget,
    bound_hint_content,
)
from sase.artifact_refs import scan_artifact_refs

_HTTP_URL_RE = re.compile(HTTP_URL_PATTERN)

# A bare bead id such as ``sase-uk.1`` or ``sase-ug.land``. Scoped to this
# checkout's own project key: generalizing to other bead stores' keys is
# tracked as a follow-up rather than risked here as a looser, more
# false-positive-prone pattern.
_BARE_BEAD_ID_RE = re.compile(
    r"(?<![\w-])sase-[0-9a-z]{1,4}(?:\.[A-Za-z0-9]+)*(?![\w-])"
)
# A bare short git sha, seven to forty lowercase hex characters.
_BARE_SHORT_SHA_RE = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")


class PagerOrigin(StrEnum):
    """What opened a pager document; seeds which bare-token rules apply.

    Bare-token recognisers are declared per origin and never globally, so
    e.g. a research document that happens to say ``sase-core`` does not
    sprout a false bead-id link.
    """

    BEAD = "bead"
    FILE = "file"
    DIFF = "diff"
    RESEARCH = "research"


class LinkSpanKind(StrEnum):
    """The scanner's four precedence-ordered span kinds, highest first."""

    ARTIFACT_REF = "artifact_ref"
    URL = "url"
    FILE_PATH = "file_path"
    BARE_TOKEN = "bare_token"


@dataclass(frozen=True, slots=True)
class LinkSpan:
    """One scanned link occurrence in a section's plain text."""

    kind: LinkSpanKind
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class BoundedLinkScan:
    """A budget-bounded scan: the content actually scanned, spans, notice."""

    content: str
    spans: tuple[LinkSpan, ...]
    notice: Text | None


def scan_links(text: str, origin: PagerOrigin) -> tuple[LinkSpan, ...]:
    """Scan *text* for precedence-ordered link spans, with no I/O."""
    occupied: list[tuple[int, int]] = []
    spans: list[LinkSpan] = []

    candidates = scan_artifact_refs(text)
    if candidates:
        byte_to_char = _byte_to_character_offsets(text)
        for candidate in candidates:
            start = byte_to_char[candidate.candidate_span.start]
            end = byte_to_char[candidate.candidate_span.end]
            occupied.append((start, end))
            if candidate.well_formed:
                spans.append(
                    LinkSpan(LinkSpanKind.ARTIFACT_REF, start, end, candidate.text)
                )

    for match in _HTTP_URL_RE.finditer(text):
        start, end = match.start(), match.end()
        if _overlaps(start, end, occupied):
            continue
        occupied.append((start, end))
        spans.append(LinkSpan(LinkSpanKind.URL, start, end, match.group(0)))

    for match in matches_outside_artifact_refs(text, iter_file_path_matches(text)):
        start, end = file_hint_match_span(match)
        if _overlaps(start, end, occupied):
            continue
        occupied.append((start, end))
        spans.append(LinkSpan(LinkSpanKind.FILE_PATH, start, end, text[start:end]))

    recognizer = _BARE_TOKEN_RECOGNIZERS.get(origin)
    if recognizer is not None:
        for match in recognizer(text):
            start, end = match.start(), match.end()
            if _overlaps(start, end, occupied):
                continue
            occupied.append((start, end))
            spans.append(LinkSpan(LinkSpanKind.BARE_TOKEN, start, end, match.group(0)))

    spans.sort(key=lambda span: span.start)
    return tuple(spans)


def scan_bounded_links(
    text: str,
    origin: PagerOrigin,
    *,
    budget: HintContentBudget | None = None,
) -> BoundedLinkScan:
    """Bound *text* to the shared hint-content budget, then scan it for links.

    Reuses ``HintContentBudget``'s 128 KB / 5,000-line caps rather than
    deriving a second budget, and surfaces the same truncation notice the
    existing hint-render path already shows.
    """
    bounded = bound_hint_content(text, budget=budget, matcher=iter_file_path_matches)
    return BoundedLinkScan(
        content=bounded.content,
        spans=scan_links(bounded.content, origin),
        notice=bounded.notice,
    )


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start < range_end and range_start < end for range_start, range_end in ranges
    )


def _byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, character in enumerate(text, start=1):
        byte_offset += len(character.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


_BARE_TOKEN_RECOGNIZERS: Mapping[
    PagerOrigin, Callable[[str], Iterator[re.Match[str]]]
] = {
    PagerOrigin.BEAD: _BARE_BEAD_ID_RE.finditer,
    PagerOrigin.DIFF: _BARE_SHORT_SHA_RE.finditer,
}
