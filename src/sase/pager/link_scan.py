"""Scan plain text for typed refs, URLs, paths, and origin-scoped bare tokens.

Rust owns document-link grammar and target normalization. This module keeps
origin-scoped bare-token recognition and Python character-offset conversion.
No I/O: a span's presence and kind derive from text alone, never from
resolving the reference it names.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
import re

from rich.text import Text

from sase.artifact_ref_operations import scan_artifact_ref_document
from sase.pager.hint_budgets import HintContentBudget, bound_hint_content
from sase.pager.path_hints import iter_pager_file_path_matches

if TYPE_CHECKING:
    from sase.artifact_ref_models import ArtifactRefDocumentTarget

# A bare bead id such as ``sase-uk.1`` or ``sase-ug.land``. Scoped to this
# checkout's own project key: generalizing to other bead stores' keys is
# tracked as a follow-up rather than risked here as a looser, more
# false-positive-prone pattern.
_BARE_BEAD_ID_RE = re.compile(
    r"(?<![\w-])sase-[0-9a-z]{1,4}(?:\.[A-Za-z0-9]+)*(?![\w-])"
)
# A bare short git sha, seven to forty lowercase hex characters.
_BARE_SHORT_SHA_RE = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")

# A UTF-8 character's first byte: any byte that is not a continuation byte.
_CHARACTER_START_RE = re.compile(rb"[^\x80-\xBF]")


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
    AGENT = "agent"


class LinkSpanKind(StrEnum):
    """The scanner's precedence-ordered span kinds, highest first."""

    ARTIFACT_REF = "artifact_ref"
    URL = "url"
    FILE_PATH = "file_path"
    MACRO_SKILL = "xprompt_skill"
    BARE_TOKEN = "bare_token"


@dataclass(frozen=True, slots=True)
class LinkSpan:
    """One scanned link occurrence in a section's plain text."""

    kind: LinkSpanKind
    start: int
    end: int
    text: str
    target: str | None = None
    semantic_target: ArtifactRefDocumentTarget | None = None


@dataclass(frozen=True, slots=True)
class BoundedLinkScan:
    """A budget-bounded scan: the content actually scanned, spans, notice."""

    content: str
    spans: tuple[LinkSpan, ...]
    notice: Text | None


def scan_links(
    text: str,
    origin: PagerOrigin,
    *,
    known_kinds: Iterable[str] = (),
) -> tuple[LinkSpan, ...]:
    """Scan *text* for precedence-ordered link spans, with no I/O.

    First-wins precedence is exact: Rust links in Rust order, then bare
    tokens in match order. Overlap checks run against an ordered-interval
    index (sorted starts plus bisect) instead of a linear scan, so
    link-dense documents stay near-linear.
    """
    spans: list[LinkSpan] = []

    scan = scan_artifact_ref_document(text, known_kinds=known_kinds)
    rust_spans: list[tuple[int, int, ArtifactRefDocumentTarget]] = []
    if scan.links:
        well_formed = [target for target in scan.links if target.well_formed]
        if well_formed:
            if text.isascii():
                # Byte offsets are character offsets; skip the table entirely.
                byte_to_char: Mapping[int, int] | None = None
            else:
                byte_to_char = _byte_to_character_offsets(
                    text,
                    _needed_byte_offsets(well_formed),
                )
            for target in well_formed:
                raw_start = target.source_span.start
                raw_end = target.source_span.end
                start = raw_start if byte_to_char is None else byte_to_char[raw_start]
                end = raw_end if byte_to_char is None else byte_to_char[raw_end]
                rust_spans.append((start, end, target))
    # First-wins greed over Rust spans in Rust order. The scanner emits
    # spans in document order, so each span overlaps the accepted set iff
    # it starts before the running maximum end: O(1) per span. An
    # out-of-order or empty span (never observed) falls back to the exact
    # linear check for the rest of the input.
    occupied: list[tuple[int, int]] = []
    ordered = True
    last_start = -1
    max_end = -1
    for start, end, target in rust_spans:
        if ordered and end > start and start >= last_start:
            last_start = start
            if start < max_end:
                continue
            max_end = max(max_end, end)
        else:
            ordered = False
            if _overlaps(start, end, occupied):
                continue
        occupied.append((start, end))
        spans.append(
            LinkSpan(
                LinkSpanKind(target.target_kind),
                start,
                end,
                target.text,
                target.target,
                target,
            )
        )

    recognizer = _BARE_TOKEN_RECOGNIZERS.get(origin)
    if recognizer is not None:
        rust_index = _FrozenSpanIndex(occupied) if ordered else None
        bare_max_end = -1
        for match in recognizer(text):
            start, end = match.start(), match.end()
            if end <= start:
                if _overlaps(start, end, occupied):
                    continue
            elif start < bare_max_end or (
                rust_index.overlaps(start, end)
                if rust_index is not None
                else _overlaps(start, end, occupied)
            ):
                continue
            bare_max_end = max(bare_max_end, end)
            occupied.append((start, end))
            spans.append(LinkSpan(LinkSpanKind.BARE_TOKEN, start, end, match.group(0)))

    spans.sort(key=lambda span: span.start)
    return tuple(spans)


def scan_bounded_links(
    text: str,
    origin: PagerOrigin,
    *,
    budget: HintContentBudget | None = None,
    known_kinds: Iterable[str] = (),
) -> BoundedLinkScan:
    """Bound *text* to the shared hint-content budget, then scan it for links.

    Reuses ``HintContentBudget``'s 128 KB / 5,000-line caps rather than
    deriving a second budget, and surfaces the same truncation notice the
    existing hint-render path already shows.
    """
    bounded = bound_hint_content(
        text, budget=budget, matcher=iter_pager_file_path_matches
    )
    return BoundedLinkScan(
        content=bounded.content,
        spans=scan_links(bounded.content, origin, known_kinds=known_kinds),
        notice=bounded.notice,
    )


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start < range_end and range_start < end for range_start, range_end in ranges
    )


class _FrozenSpanIndex:
    """Bisect-based overlap queries over an accepted, start-sorted span list.

    ``starts`` is sorted and ``prefix_max_ends[i]`` is the maximum end over
    ``spans[:i + 1]``. A candidate ``(start, end)`` overlaps the set iff the
    spans starting strictly before ``end`` reach past ``start``.
    """

    __slots__ = ("prefix_max_ends", "starts")

    def __init__(self, spans: list[tuple[int, int]]) -> None:
        starts: list[int] = []
        prefix_max_ends: list[int] = []
        running = -1
        for span_start, span_end in spans:
            starts.append(span_start)
            running = max(running, span_end)
            prefix_max_ends.append(running)
        self.starts = starts
        self.prefix_max_ends = prefix_max_ends

    def overlaps(self, start: int, end: int) -> bool:
        """Return whether ``(start, end)`` overlaps any indexed span."""
        index = bisect_left(self.starts, end)
        return index > 0 and self.prefix_max_ends[index - 1] > start


def _needed_byte_offsets(
    targets: list[ArtifactRefDocumentTarget],
) -> list[int]:
    """Return the sorted byte offsets the scan must convert to characters."""
    needed = {target.source_span.start for target in targets}
    needed.update(target.source_span.end for target in targets)
    return sorted(needed)


def _byte_to_character_offsets(text: str, needed: list[int]) -> dict[int, int]:
    """Map each needed UTF-8 byte offset in *text* to a character offset.

    Only the requested offsets are mapped: the text is encoded once and
    character-start byte positions are found with a byte-level scan, so a
    document pays for its links rather than for its characters.
    """
    raw = text.encode("utf-8")
    # Every character's first byte is not a UTF-8 continuation byte; the
    # match positions are exactly the character-boundary byte offsets.
    boundaries = [match.start() for match in _CHARACTER_START_RE.finditer(raw)]
    total = len(raw)
    mapping: dict[int, int] = {}
    for offset in needed:
        if offset == total:
            mapping[offset] = len(text)
            continue
        index = bisect_left(boundaries, offset)
        if index >= len(boundaries) or boundaries[index] != offset:
            raise KeyError(offset)
        mapping[offset] = index
    return mapping


_BARE_TOKEN_RECOGNIZERS: Mapping[
    PagerOrigin, Callable[[str], Iterator[re.Match[str]]]
] = {
    PagerOrigin.BEAD: _BARE_BEAD_ID_RE.finditer,
    PagerOrigin.DIFF: _BARE_SHORT_SHA_RE.finditer,
    # Agent metadata documents treat bare bead ids exactly like bead
    # documents (the BEAD section's own id is a bare token in its heading).
    PagerOrigin.AGENT: _BARE_BEAD_ID_RE.finditer,
}
