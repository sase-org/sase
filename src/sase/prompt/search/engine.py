"""The deterministic prompt-search engine: match, filter, rank, limit.

:func:`search_prompts` is a pure function over a pre-loaded
:class:`~sase.prompt.search.model.PromptHit` corpus. It does no IO and no
rendering — discovery is the sources layer's job, presentation is the CLI's.
Given a query and the filter knobs that mirror the ``sase prompt search`` flag
set, it returns a :class:`~sase.prompt.search.model.PromptSearchResult` carrying
the ranked, post-limit matches plus the pre-limit ``total`` and per-source
``counts`` so truncation is always reportable.

The contract is deliberately predictable (the "reliable" requirement):

- **Matching** is a case-insensitive Unicode substring test of the literal
  query against every human-readable field, with the matched fields recorded so
  the renderers can explain *why* a hit matched.
- **Filters** (source, date range, tags, cancelled-only) AND together.
- **Ranking** is fully deterministic: source priority → match tier → recency →
  a stable locator tiebreak, so output is byte-stable across runs.
"""

from __future__ import annotations

from collections.abc import Iterable

from sase.prompt.search.dates import hit_date
from sase.prompt.search.model import (
    PromptHit,
    PromptSearchMatch,
    PromptSearchResult,
    PromptSource,
)

# Every source, used to default an empty ``sources`` filter to "all" and to seed
# the per-source counts so each source is always reported (even as ``0``).
_ALL_SOURCES: frozenset[PromptSource] = frozenset(PromptSource.__members__.values())
# A match in any of these outranks a body/plan/tag-only hit (the "match tier").
_STRONG_FIELDS = frozenset({"title", "id", "path"})
# Sigils stripped when normalizing a ``--tag`` value, matching how the sources
# layer normalizes the tags stored on a hit (so ``--tag '#review'`` still hits).
_TAG_SIGILS = "#@"
# Oldest-sortable recency value for an undated hit, so it ranks last.
_RECENCY_FLOOR = 0


class EmptyPromptQueryError(ValueError):
    """Raised when a prompt-search query is empty or whitespace-only.

    The CLI translates this into a usage error (exit ``2``), mirroring
    ``sase bead search``; the engine raises it so the contract is enforced for
    every caller, not just the CLI.
    """

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__("Prompt search query must not be empty.")


def search_prompts(
    query: str,
    hits: Iterable[PromptHit],
    *,
    sources: Iterable[PromptSource] = (),
    after: str | None = None,
    before: str | None = None,
    tags: Iterable[str] = (),
    cancelled_only: bool = False,
    limit: int = 0,
) -> PromptSearchResult:
    """Search *hits* for *query* and return a ranked, bounded result envelope.

    Args:
        query: The literal substring to search for. Leading/trailing whitespace
            is ignored; an empty or whitespace-only query is a usage error.
        hits: The unified corpus to search (typically from
            :func:`~sase.prompt.search.sources.collect_prompt_hits`).
        sources: Restrict results to these sources. Empty means *all* sources.
        after: Inclusive lower date bound as a comparable ``YYmmdd_HHMMSS``
            anchor (from :func:`~sase.prompt.search.dates.parse_search_date`), or
            ``None`` for no lower bound.
        before: Inclusive upper date bound, same shape as *after*, or ``None``.
        tags: Keep only hits carrying *any* of these tags (OR across repeats),
            compared case-insensitively after sigil-stripping. Empty disables the
            tag filter.
        cancelled_only: Restrict **local** hits to cancelled prompts. Archive
            hits have no cancelled state and are unaffected.
        limit: Cap the number of **shown** matches after ranking. ``<= 0`` means
            unlimited. The pre-limit ``total`` and per-source ``counts`` are
            always reported regardless of *limit*.

    Returns:
        A :class:`~sase.prompt.search.model.PromptSearchResult` whose ``matches``
        are ranked and truncated to *limit*, with ``total`` and ``counts``
        describing the full pre-limit match set.

    Raises:
        EmptyPromptQueryError: *query* is empty or whitespace-only.
    """
    needle = query.strip()
    if not needle:
        raise EmptyPromptQueryError(query)

    selected = frozenset(sources) or _ALL_SOURCES
    folded_needle = needle.casefold()
    wanted_tags = _normalize_tags(tags)

    matches: list[PromptSearchMatch] = []
    counts: dict[PromptSource, int] = dict.fromkeys(_ALL_SOURCES, 0)
    for hit in hits:
        if not _passes_filters(
            hit, selected, after, before, wanted_tags, cancelled_only
        ):
            continue
        matched_fields = _matched_fields(hit, folded_needle)
        if not matched_fields:
            continue
        matches.append(PromptSearchMatch(hit=hit, matched_fields=matched_fields))
        counts[hit.source] += 1

    ranked = sorted(matches, key=_rank_key)
    shown = ranked if limit <= 0 else ranked[:limit]
    return PromptSearchResult(
        query=needle,
        matches=tuple(shown),
        total=len(ranked),
        counts=counts,
    )


# ---------------------------------------------------------------------------
# Filtering (AND across every active filter)
# ---------------------------------------------------------------------------


def _passes_filters(
    hit: PromptHit,
    selected: frozenset[PromptSource],
    after: str | None,
    before: str | None,
    wanted_tags: frozenset[str],
    cancelled_only: bool,
) -> bool:
    """Return whether *hit* survives every active filter."""
    if hit.source not in selected:
        return False
    if not _within_dates(hit, after, before):
        return False
    if wanted_tags and not _has_any_tag(hit, wanted_tags):
        return False
    if cancelled_only and hit.source is PromptSource.LOCAL and not hit.cancelled:
        return False
    return True


def _within_dates(hit: PromptHit, after: str | None, before: str | None) -> bool:
    """Return whether *hit*'s date falls within the inclusive ``[after, before]``."""
    date = hit_date(hit)
    if after is not None and date < after:
        return False
    if before is not None and date > before:
        return False
    return True


def _has_any_tag(hit: PromptHit, wanted: frozenset[str]) -> bool:
    """Return whether *hit* carries any of the *wanted* (normalized) tags."""
    return any(tag.casefold() in wanted for tag in hit.tags)


def _normalize_tags(tags: Iterable[str]) -> frozenset[str]:
    """Normalize requested tags to sigil-stripped, case-folded tokens."""
    normalized: set[str] = set()
    for tag in tags:
        token = tag.strip().lstrip(_TAG_SIGILS).strip().casefold()
        if token:
            normalized.add(token)
    return frozenset(normalized)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _matched_fields(hit: PromptHit, needle: str) -> tuple[str, ...]:
    """Return the fields of *hit* containing *needle*, in stable field order.

    *needle* must already be case-folded; each field is folded before the
    substring test so matching is case-insensitive and Unicode-aware. The
    ``candidates`` tuple fixes the field order (``title``, ``body``, ``id``,
    ``path``, ``plan``); the ``tags`` token, when present, is appended last.
    """
    candidates: tuple[tuple[str, str | None], ...] = (
        ("title", hit.title),
        ("body", hit.text),
        ("id", hit.id),
        ("path", hit.path),
        ("plan", hit.plan),
    )
    fields = [
        name for name, value in candidates if value and needle in value.casefold()
    ]
    if any(needle in tag.casefold() for tag in hit.tags):
        fields.append("tags")
    return tuple(fields)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _rank_key(match: PromptSearchMatch) -> tuple[int, int, int, tuple[str, str]]:
    """Return the deterministic sort key for *match* (ascending sort).

    Ordering, most significant first:

    1. **Source priority** — canonical archive before local.
    2. **Match tier** — a strong-field hit (title/locator/path) before a
       body/plan/tag-only hit.
    3. **Recency** — newer date first (the date is negated so a plain ascending
       sort puts the newest hit on top).
    4. **Stable tiebreak** — locator/path, so output is byte-stable.
    """
    hit = match.hit
    return (
        _source_priority(hit.source),
        _match_tier(match.matched_fields),
        _recency_key(hit),
        (hit.path or "", hit.id),
    )


def _source_priority(source: PromptSource) -> int:
    """Return ``0`` for the archive (ranked first) and ``1`` for local."""
    return 0 if source is PromptSource.ARCHIVE else 1


def _match_tier(matched_fields: tuple[str, ...]) -> int:
    """Return ``0`` when a strong field matched, else ``1``."""
    return 0 if any(field in _STRONG_FIELDS for field in matched_fields) else 1


def _recency_key(hit: PromptHit) -> int:
    """Return a negated numeric date so newer hits sort first; floor when unset."""
    digits = hit_date(hit).replace("_", "")
    try:
        return -int(digits)
    except ValueError:
        return _RECENCY_FLOOR
