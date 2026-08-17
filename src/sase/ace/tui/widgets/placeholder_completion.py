"""Pure mapping from Rust placeholder payloads to prompt completion rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.history.prompt_placeholder_ranking import (
    RankedPlaceholder,
    build_placeholder_ranking_context,
    rank_common_placeholders,
    rank_recent_common_placeholders,
)
from sase.history.prompt_placeholders import CommonPlaceholderIndex
from sase.xprompt.placeholder_completion import (
    PlaceholderCandidateSource,
    PlaceholderPosition,
    PlaceholderRange,
    placeholder_completion,
)

PLACEHOLDER_COMPLETION_KIND = "placeholder"


@dataclass(frozen=True, slots=True)
class PlaceholderRankingMetadata:
    """Ranking evidence carried by one smart-ranked saved placeholder."""

    reason: str
    related_to: str
    use_count: int
    age_seconds: float
    score: float
    relation: float
    recency: float
    frequency: float


@dataclass(frozen=True, slots=True)
class PlaceholderCompletionMetadata:
    """Row metadata telling the panel which source produced a candidate."""

    source: PlaceholderCandidateSource
    ranking: PlaceholderRankingMetadata | None = None


@dataclass(frozen=True, slots=True)
class PlaceholderCompletionResult:
    """Prompt-local offsets and candidates for one placeholder context."""

    prefix: str
    replacement_start: int
    replacement_end: int
    append_closing_bracket: bool
    candidates: list[CompletionCandidate]


def placeholder_lone_leading_match(
    result: PlaceholderCompletionResult,
) -> bool:
    """Return whether the highest-priority source group has one candidate."""
    if not result.candidates:
        return False

    first_source = _placeholder_candidate_source(result.candidates[0])
    leading_count = 0
    for candidate in result.candidates:
        if _placeholder_candidate_source(candidate) != first_source:
            break
        leading_count += 1
    return leading_count == 1


def build_placeholder_completion_result(
    text: str,
    cursor_offset: int,
    common: Sequence[str] = (),
    *,
    include_common_when_prefix_empty: bool = False,
) -> PlaceholderCompletionResult | None:
    """Return placeholder completions at a Python character offset.

    Core always receives ``common`` and owns every matching, dedup, and
    ordering rule.  The only thing decided here is whether a bare ``<`` gets to
    see the saved group at all: an automatic trigger keeps quiet until the user
    types a prefix, while an explicit ``Ctrl+T`` shows the full list.  That is a
    filter over an already-merged list, not a second matching implementation.
    """
    return _placeholder_completion_result(
        text,
        cursor_offset,
        common,
        include_common_when_prefix_empty=include_common_when_prefix_empty,
        ranking_by_text=None,
    )


def build_indexed_placeholder_completion_result(
    text: str,
    cursor_offset: int,
    index: CommonPlaceholderIndex,
    *,
    now: float,
    smart: bool,
    include_common_when_prefix_empty: bool = False,
) -> PlaceholderCompletionResult | None:
    """Return placeholder completions ranked from a warm store index.

    Ranks the whole store, then hands the ordered texts to the Rust engine as
    ``common`` so prefix filtering, prompt-group dedup, and the replacement
    range stay in one place.  Smart mode reattaches ranking evidence to each
    returned ``common`` candidate by exact text; ``recent`` mode and prompt
    candidates carry none.
    """
    if smart:
        context = build_placeholder_ranking_context(index, text, now=now)
        ranked = rank_common_placeholders(index, context, now=now)
        ranking_by_text = {item.text: item for item in ranked}
    else:
        ranked = rank_recent_common_placeholders(index, now=now)
        ranking_by_text = None
    return _placeholder_completion_result(
        text,
        cursor_offset,
        [item.text for item in ranked],
        include_common_when_prefix_empty=include_common_when_prefix_empty,
        ranking_by_text=ranking_by_text,
    )


def _placeholder_completion_result(
    text: str,
    cursor_offset: int,
    common: Sequence[str],
    *,
    include_common_when_prefix_empty: bool,
    ranking_by_text: Mapping[str, RankedPlaceholder] | None,
) -> PlaceholderCompletionResult | None:
    position = _editor_position_for_offset(text, cursor_offset)
    if position is None:
        return None
    payload = placeholder_completion(
        text,
        position.line,
        position.character,
        common,
    )
    if payload is None:
        return None
    replacement = editor_range_to_offsets(text, payload.replacement_range)
    if replacement is None:
        return None
    replacement_start, replacement_end = replacement
    drop_common = not payload.prefix and not include_common_when_prefix_empty
    candidates = [
        CompletionCandidate(
            display=candidate.text,
            insertion=candidate.text,
            is_dir=False,
            name=candidate.text,
            metadata=PlaceholderCompletionMetadata(
                source=candidate.source,
                ranking=_ranking_metadata(
                    candidate.text,
                    candidate.source,
                    ranking_by_text,
                ),
            ),
        )
        for candidate in payload.candidates
        if not (drop_common and candidate.source == "common")
    ]
    if not candidates:
        return None
    return PlaceholderCompletionResult(
        prefix=payload.prefix,
        replacement_start=replacement_start,
        replacement_end=replacement_end,
        append_closing_bracket=payload.append_closing_bracket,
        candidates=candidates,
    )


def _ranking_metadata(
    text: str,
    source: PlaceholderCandidateSource,
    ranking_by_text: Mapping[str, RankedPlaceholder] | None,
) -> PlaceholderRankingMetadata | None:
    if ranking_by_text is None or source != "common":
        return None
    item = ranking_by_text.get(text)
    if item is None:
        return None
    return PlaceholderRankingMetadata(
        reason=item.reason,
        related_to=item.related_to,
        use_count=item.use_count,
        age_seconds=item.age_seconds,
        score=item.score,
        relation=item.relation,
        recency=item.recency,
        frequency=item.frequency,
    )


def _placeholder_candidate_source(
    candidate: CompletionCandidate,
) -> PlaceholderCandidateSource:
    """Read source metadata, defaulting malformed rows to prompt-local."""
    metadata = candidate.metadata
    if isinstance(metadata, PlaceholderCompletionMetadata):
        return metadata.source
    return "prompt"


def _editor_position_for_offset(
    text: str,
    offset: int,
) -> PlaceholderPosition | None:
    """Convert a Python character offset to an LSP UTF-16 position."""
    if offset < 0 or offset > len(text):
        return None
    line_start = text.rfind("\n", 0, offset) + 1
    line = text.count("\n", 0, line_start)
    character = sum(_utf16_width(char) for char in text[line_start:offset])
    return PlaceholderPosition(line=line, character=character)


def _editor_position_to_offset(
    text: str,
    position: PlaceholderPosition,
) -> int | None:
    """Convert an LSP UTF-16 position to a Python character offset."""
    if position.line < 0 or position.character < 0:
        return None
    line_start = 0
    for _ in range(position.line):
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1

    newline = text.find("\n", line_start)
    line_end = len(text) if newline == -1 else newline
    if line_end > line_start and text[line_end - 1] == "\r":
        line_end -= 1

    units = 0
    for offset, char in enumerate(text[line_start:line_end]):
        if units == position.character:
            return line_start + offset
        width = _utf16_width(char)
        if units + width > position.character:
            return None
        units += width
    if units == position.character:
        return line_end
    return None


def editor_range_to_offsets(
    text: str,
    span: PlaceholderRange,
) -> tuple[int, int] | None:
    """Convert an LSP range to Python character offsets."""
    start = _editor_position_to_offset(text, span.start)
    end = _editor_position_to_offset(text, span.end)
    if start is None or end is None or end < start:
        return None
    return start, end


def _utf16_width(char: str) -> int:
    return 2 if ord(char) > 0xFFFF else 1
