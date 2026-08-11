"""Bead candidate catalog and validation for the Agents-tab Wait modal.

Presentation-free by design: no Rich, no Textual. The candidate ranking and
selection classification here are the part that would move to
``../sase-core`` if another frontend ever needed "beads this agent may wait
on".
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from threading import RLock

from sase.bead.model import Issue
from sase.bead.store_locator import (
    canonical_beads_dir_for_project,
    closed_bead_ids_for_project,
    open_bead_candidates_for_project,
)
from sase.bead_status_presentation import bead_status_presentation

WAIT_BEAD_PREVIEW_NEUTRAL = "wait-time-neutral"
WAIT_BEAD_PREVIEW_VALID = "wait-time-valid"
WAIT_BEAD_PREVIEW_ERROR = "wait-time-error"

_MAX_PREVIEW_ENTRIES = 3
_STATUS_RANK: dict[str, int] = {
    "in_progress": 0,
    "claimed": 1,
    "ready": 2,
    "open": 3,
    "snoozed": 4,
}
_RAW_CACHE_MAX_ENTRIES = 32


@dataclass(frozen=True, slots=True)
class WaitBeadCandidate:
    """One selectable bead row for the Wait modal's beads completion list."""

    bead_id: str
    title: str
    status: str
    type_label: str
    created_at: str
    updated_at: str

    @property
    def search_text(self) -> str:
        return " ".join((self.bead_id, self.title)).lower()


@dataclass(frozen=True)
class WaitBeadCatalog:
    """Candidate beads for one project, plus store-availability state."""

    candidates: tuple[WaitBeadCandidate, ...] = ()
    available: bool = False
    closed_ids: frozenset[str] = frozenset()

    @cached_property
    def by_id(self) -> dict[str, WaitBeadCandidate]:
        """Return non-closed candidates keyed by bead ID."""
        return {candidate.bead_id: candidate for candidate in self.candidates}


@dataclass(frozen=True, slots=True)
class _WaitBeadCandidateResults:
    """Bounded, filtered candidate rows plus the number omitted by the cap."""

    rows: tuple[WaitBeadCandidate, ...]
    omitted: int


@dataclass(frozen=True, slots=True)
class _WaitBeadSelectionPreview:
    """Live-preview classification of the beads currently typed in the field."""

    css_class: str
    message: str
    guard_armed: bool = False


@dataclass(frozen=True, slots=True)
class _RawCatalogEntry:
    token: tuple[int, int] | None
    issues: tuple[Issue, ...]
    closed_ids: frozenset[str]
    available: bool


_RAW_CACHE: OrderedDict[str, _RawCatalogEntry] = OrderedDict()
_RAW_CACHE_LOCK = RLock()


def _index_token(project_key: str) -> tuple[int, int] | None:
    beads_dir = canonical_beads_dir_for_project(project_key)
    if beads_dir is None:
        return None
    try:
        stat = (beads_dir / "issues.jsonl").stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _load_raw_catalog(project_key: str) -> _RawCatalogEntry:
    """Return the cached raw store read, revalidating by mtime/size."""
    token = _index_token(project_key)
    with _RAW_CACHE_LOCK:
        cached = _RAW_CACHE.get(project_key)
        if cached is not None and token is not None and cached.token == token:
            _RAW_CACHE.move_to_end(project_key)
            return cached

    issues = open_bead_candidates_for_project(project_key)
    if issues is None:
        entry = _RawCatalogEntry(
            token=token,
            issues=(),
            closed_ids=frozenset(),
            available=False,
        )
    else:
        entry = _RawCatalogEntry(
            token=token,
            issues=issues,
            closed_ids=closed_bead_ids_for_project(project_key) or frozenset(),
            available=True,
        )

    with _RAW_CACHE_LOCK:
        _RAW_CACHE[project_key] = entry
        _RAW_CACHE.move_to_end(project_key)
        while len(_RAW_CACHE) > _RAW_CACHE_MAX_ENTRIES:
            _RAW_CACHE.popitem(last=False)
    return entry


def _bead_candidate(issue: Issue) -> WaitBeadCandidate:
    return WaitBeadCandidate(
        bead_id=issue.id,
        title=issue.title,
        status=issue.status.value,
        type_label=issue.issue_type.value,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )


def _ordered_candidates(
    candidates: Iterable[WaitBeadCandidate],
) -> tuple[WaitBeadCandidate, ...]:
    """Order by status rank, then ``updated_at`` descending, then ID."""
    ordered = sorted(candidates, key=lambda candidate: candidate.bead_id)
    ordered.sort(key=lambda candidate: candidate.updated_at, reverse=True)
    ordered.sort(
        key=lambda candidate: _STATUS_RANK.get(candidate.status, len(_STATUS_RANK))
    )
    return tuple(ordered)


def load_wait_bead_catalog(
    project_key: str | None,
    *,
    own_bead_ids: frozenset[str] = frozenset(),
) -> WaitBeadCatalog:
    """Load the wait-bead catalog for *project_key*.

    Worker-thread entry point: this touches the bead store and must only be
    called off the Textual event loop.
    """
    if not project_key:
        return WaitBeadCatalog()

    raw = _load_raw_catalog(project_key)
    if not raw.available:
        return WaitBeadCatalog()

    candidates = _ordered_candidates(
        _bead_candidate(issue) for issue in raw.issues if issue.id not in own_bead_ids
    )
    return WaitBeadCatalog(
        candidates=candidates,
        available=True,
        closed_ids=raw.closed_ids,
    )


def filter_wait_bead_candidates(
    catalog: WaitBeadCatalog,
    fragment: str,
    *,
    limit: int = 100,
) -> _WaitBeadCandidateResults:
    """Return bounded, filtered candidate rows plus the omitted count."""
    fragment = fragment.strip().lower()
    matches = (
        [
            candidate
            for candidate in catalog.candidates
            if fragment in candidate.search_text
        ]
        if fragment
        else list(catalog.candidates)
    )
    return _WaitBeadCandidateResults(
        rows=tuple(matches[:limit]),
        omitted=max(0, len(matches) - limit),
    )


def classify_wait_bead_selection(
    catalog: WaitBeadCatalog | None,
    bead_ids: Sequence[str],
    *,
    own_bead_ids: frozenset[str] = frozenset(),
    project_label: str = "",
) -> _WaitBeadSelectionPreview:
    """Classify the typed bead-wait selection for the live preview.

    ``catalog=None`` means the catalog is still loading, distinct from a
    loaded-but-unavailable catalog (``WaitBeadCatalog(available=False)``).
    """
    ordered_ids = list(dict.fromkeys(bead_ids))
    if not ordered_ids:
        return _WaitBeadSelectionPreview(
            css_class=WAIT_BEAD_PREVIEW_NEUTRAL,
            message="starts when every listed bead is closed",
        )
    if catalog is None:
        label = f"{project_label} " if project_label else ""
        return _WaitBeadSelectionPreview(
            css_class=WAIT_BEAD_PREVIEW_NEUTRAL,
            message=f"loading {label}beads…",
        )
    if not catalog.available:
        return _WaitBeadSelectionPreview(
            css_class=WAIT_BEAD_PREVIEW_NEUTRAL,
            message="bead store unavailable — IDs not verified",
        )

    for bead_id in ordered_ids:
        if bead_id in own_bead_ids:
            return _WaitBeadSelectionPreview(
                css_class=WAIT_BEAD_PREVIEW_ERROR,
                message=(
                    f"{bead_id} is this agent's own bead — it can never close first"
                ),
                guard_armed=True,
            )
        if bead_id not in catalog.by_id and bead_id not in catalog.closed_ids:
            label = project_label or "the project"
            return _WaitBeadSelectionPreview(
                css_class=WAIT_BEAD_PREVIEW_ERROR,
                message=(
                    f"{bead_id} is not in {label}'s bead store — "
                    "the agent would park forever"
                ),
                guard_armed=True,
            )

    entries: list[str] = []
    for bead_id in ordered_ids[:_MAX_PREVIEW_ENTRIES]:
        candidate = catalog.by_id.get(bead_id)
        status = candidate.status if candidate is not None else "closed"
        presentation = bead_status_presentation(status)
        entries.append(f"{bead_id} {presentation.tui_glyph} {presentation.label}")
    if len(ordered_ids) > _MAX_PREVIEW_ENTRIES:
        entries.append(f"+{len(ordered_ids) - _MAX_PREVIEW_ENTRIES} more")

    known_statuses = [
        candidate.status
        for bead_id in ordered_ids
        if (candidate := catalog.by_id.get(bead_id)) is not None
    ]
    open_count = known_statuses.count("open")
    in_progress_count = known_statuses.count("in_progress")
    aggregate = f"{len(ordered_ids)} beads · {open_count} open · {in_progress_count} in progress"
    message = f"{', '.join(entries)} · {aggregate}"

    closed_typed = [bead_id for bead_id in ordered_ids if bead_id in catalog.closed_ids]
    if closed_typed:
        closed_note = "; ".join(
            f"{bead_id} is already closed — it will not hold the launch"
            for bead_id in closed_typed
        )
        message = f"{message}. {closed_note}"

    return _WaitBeadSelectionPreview(css_class=WAIT_BEAD_PREVIEW_VALID, message=message)


__all__ = [
    "WAIT_BEAD_PREVIEW_ERROR",
    "WAIT_BEAD_PREVIEW_NEUTRAL",
    "WAIT_BEAD_PREVIEW_VALID",
    "WaitBeadCandidate",
    "WaitBeadCatalog",
    "classify_wait_bead_selection",
    "filter_wait_bead_candidates",
    "load_wait_bead_catalog",
]
