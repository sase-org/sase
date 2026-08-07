"""Pure filtering logic for the Help panel's live keymap filter bar."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sase.core.fuzzy_facade import FuzzyMatch, fuzzy_match

from .binding_common import Sections

Token = str

_CONTIGUOUS_MAX_TIER = 2
_SCATTERED_MAX_TIER = 3


@dataclass(frozen=True, slots=True)
class FilteredRow:
    """A single keybinding row that survived filtering."""

    key: str
    description: str
    key_runs: tuple[tuple[int, int], ...]
    description_runs: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _FilteredSection:
    """A keybinding section that survived filtering, with matched rows only."""

    name: str
    name_runs: tuple[tuple[int, int], ...]
    rows: tuple[FilteredRow, ...]


@dataclass(frozen=True, slots=True)
class FilterResult:
    """The outcome of filtering the full set of keybinding sections."""

    query: str
    active: bool
    sections: tuple[_FilteredSection, ...]
    keymap_count: int
    section_count: int
    relaxed: bool


def tokenize(query: str) -> tuple[Token, ...]:
    """Split a filter query into whitespace-separated tokens."""
    return tuple(query.split())


def filter_sections(sections: Sections, query: str) -> FilterResult:
    """Filter *sections* against *query*, ANDing tokens across three haystacks.

    Pass 1 accepts only contiguous fuzzy matches. If it yields no rows, pass 2
    relaxes to scattered-subsequence matches so initialisms like ``bp`` still
    find ``Beads Pane``.
    """
    tokens = tokenize(query)
    if not tokens:
        return FilterResult(
            query=query,
            active=False,
            sections=(),
            keymap_count=0,
            section_count=0,
            relaxed=False,
        )

    filtered, keymap_count = _filter_pass(sections, tokens, _CONTIGUOUS_MAX_TIER)
    relaxed = False
    if keymap_count == 0:
        relaxed_filtered, relaxed_count = _filter_pass(
            sections, tokens, _SCATTERED_MAX_TIER
        )
        if relaxed_count > 0:
            filtered, keymap_count = relaxed_filtered, relaxed_count
            relaxed = True

    return FilterResult(
        query=query,
        active=True,
        sections=tuple(filtered),
        keymap_count=keymap_count,
        section_count=len(filtered),
        relaxed=relaxed,
    )


def matches_title(title: str, query: str) -> tuple[tuple[int, int], ...] | None:
    """Return merged match runs when every token in *query* matches *title*."""
    tokens = tokenize(query)
    if not tokens:
        return None
    runs: list[tuple[int, int]] = []
    for token in tokens:
        match = fuzzy_match(token, title)
        if match is None:
            return None
        runs.extend(match.runs)
    return tuple(runs)


def balance_split(sections: Sequence[_FilteredSection], *, lead_lines: int = 0) -> int:
    """Return the index where the right column should start.

    Each section renders as ``len(rows) + 3`` lines (blank line, header,
    rows, footer). *lead_lines* accounts for query panels already placed in
    the left column.
    """
    section_lines = [len(section.rows) + 3 for section in sections]
    left_lines = lead_lines
    right_lines = sum(section_lines)

    best_index = 0
    best_diff = abs(left_lines - right_lines)
    for index, lines in enumerate(section_lines):
        left_lines += lines
        right_lines -= lines
        diff = abs(left_lines - right_lines)
        if diff < best_diff:
            best_diff = diff
            best_index = index + 1

    return best_index


def _filter_pass(
    sections: Sections, tokens: tuple[Token, ...], max_tier: int
) -> tuple[list[_FilteredSection], int]:
    result: list[_FilteredSection] = []
    keymap_count = 0

    for name, rows in sections:
        name_hits = [_fuzzy(token, name, max_tier) for token in tokens]
        satisfied_by_name = {i for i, hit in enumerate(name_hits) if hit is not None}
        name_runs = _merge_runs(hit.runs for hit in name_hits if hit is not None)

        filtered_rows: list[FilteredRow] = []
        for key, description in rows:
            key_run_groups: list[tuple[tuple[int, int], ...]] = []
            description_run_groups: list[tuple[tuple[int, int], ...]] = []
            row_matches = True
            for i, token in enumerate(tokens):
                if i in satisfied_by_name:
                    continue
                key_hit = _fuzzy(token, key, max_tier)
                description_hit = _fuzzy(token, description, max_tier)
                if key_hit is None and description_hit is None:
                    row_matches = False
                    break
                if key_hit is not None:
                    key_run_groups.append(key_hit.runs)
                if description_hit is not None:
                    description_run_groups.append(description_hit.runs)
            if not row_matches:
                continue
            filtered_rows.append(
                FilteredRow(
                    key=key,
                    description=description,
                    key_runs=_merge_runs(key_run_groups),
                    description_runs=_merge_runs(description_run_groups),
                )
            )

        if filtered_rows:
            result.append(
                _FilteredSection(
                    name=name,
                    name_runs=name_runs,
                    rows=tuple(filtered_rows),
                )
            )
            keymap_count += len(filtered_rows)

    return result, keymap_count


def _fuzzy(token: Token, text: str, max_tier: int) -> FuzzyMatch | None:
    match = fuzzy_match(token, text)
    if match is None or match.tier > max_tier:
        return None
    return match


def _merge_runs(
    groups: Iterable[tuple[tuple[int, int], ...]],
) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for group in groups:
        merged.extend(group)
    return tuple(merged)


__all__ = [
    "FilterResult",
    "FilteredRow",
    "Token",
    "balance_split",
    "filter_sections",
    "matches_title",
    "tokenize",
]
