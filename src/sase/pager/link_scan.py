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
from functools import lru_cache
from typing import TYPE_CHECKING
import re

from rich.text import Text

from sase.artifact_ref_operations import scan_artifact_ref_document
from sase.pager.hint_budgets import HintContentBudget, bound_hint_content
from sase.pager.path_hints import iter_pager_file_path_matches

if TYPE_CHECKING:
    from sase.artifact_ref_models import ArtifactRefDocumentTarget

# Fallback bare bead-ID prefixes for sections that declare none. Covers
# tool-run log documents and any other AGENT/BEAD producer that does not
# stamp per-document prefixes.
DEFAULT_BARE_BEAD_ID_PREFIXES: tuple[str, ...] = ("sase",)


def normalize_bead_id_prefixes(prefixes: Iterable[str]) -> tuple[str, ...]:
    """Normalize bead-ID prefixes into a stable, sorted tuple.

    Each value is stripped; empty or unsafe values are dropped. Unsafe
    matches ``sase.bead.prefix_policy._is_safe_bead_prefix`` (whitespace,
    ``.``, ``/``, ``\\``, ``--``, or a trailing ``-``) and is re-implemented
    here so the cold path does not import the bead package.
    """

    def _is_safe(prefix: str) -> bool:
        if not prefix:
            return False
        if any(char.isspace() for char in prefix):
            return False
        if "." in prefix or "/" in prefix or "\\" in prefix:
            return False
        if "--" in prefix:
            return False
        if prefix.endswith("-"):
            return False
        return True

    seen: set[str] = set()
    for raw in prefixes:
        cleaned = raw.strip()
        if not cleaned or not _is_safe(cleaned):
            continue
        seen.add(cleaned)
    return tuple(sorted(seen))


@lru_cache(maxsize=64)
def _bare_bead_id_regex(prefixes: tuple[str, ...]) -> re.Pattern[str]:
    """Compile the bare bead-ID pattern for one normalized prefix tuple."""
    ordered = sorted(prefixes, key=lambda part: (-len(part), part))
    alternation = "|".join(re.escape(part) for part in ordered)
    return re.compile(
        rf"(?<![\w-])(?:{alternation})-[0-9a-z]{{1,4}}(?:\.[A-Za-z0-9]+)*(?![\w-])"
    )


# A bare short git sha, seven to forty lowercase hex characters.
_BARE_SHORT_SHA_RE = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")


def is_bare_short_sha(text: str) -> bool:
    """Return whether *text* is exactly one bare short SHA."""
    return _BARE_SHORT_SHA_RE.fullmatch(text) is not None


def _bare_token_recognizer(
    origin: PagerOrigin,
    bead_id_prefixes: Iterable[str] = (),
) -> Callable[[str], Iterator[re.Match[str]]] | None:
    """Return the bare-token recognizer for *origin*, or ``None``.

    BEAD and AGENT origins recognize bare bead IDs for the given prefixes
    (falling back to ``DEFAULT_BARE_BEAD_ID_PREFIXES`` when none survive
    normalization). DIFF recognizes bare short SHAs. Every other origin
    recognizes no bare tokens.
    """
    if origin in (PagerOrigin.BEAD, PagerOrigin.AGENT):
        normalized = normalize_bead_id_prefixes(bead_id_prefixes)
        if not normalized:
            normalized = DEFAULT_BARE_BEAD_ID_PREFIXES
        return _bare_bead_id_regex(normalized).finditer
    if origin is PagerOrigin.DIFF:
        return _BARE_SHORT_SHA_RE.finditer
    return None


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
    MACRO_SKILL = "macro_skill"
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
    bead_id_prefixes: Iterable[str] = (),
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

    recognizer = _bare_token_recognizer(origin, bead_id_prefixes)
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
    bead_id_prefixes: Iterable[str] = (),
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
        spans=scan_links(
            bounded.content,
            origin,
            known_kinds=known_kinds,
            bead_id_prefixes=bead_id_prefixes,
        ),
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
