"""Pure request, fetch, and reconciliation helpers for deep plan archives."""

from __future__ import annotations

from dataclasses import dataclass

from sase.plan_search.filter_query import PlanFilterValues

from .plans_data import (
    DEEP_ARCHIVE_PER_PROJECT_LIMIT,
    PlansSnapshot,
    ProjectArchive,
    load_deep_plan_archive,
)
from .plans_filtering import (
    build_plan_archive_filter_records,
    compile_plan_matcher,
)

DEEP_ARCHIVE_DEBOUNCE_S = 0.3
DEEP_ARCHIVE_CACHE_LIMIT = 32


@dataclass(frozen=True)
class DeepArchiveRequest:
    """Identity for one last-request-wins archive reconciliation."""

    project_scope: str | None
    values: PlanFilterValues
    snapshot_identity: int
    project_roots: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DeepArchiveResult:
    """Matched display rows from one bounded archive browse."""

    request: DeepArchiveRequest
    archive: tuple[ProjectArchive, ...]
    scanned_count: int
    capped: bool
    errors: tuple[tuple[str, str], ...]

    @property
    def exact(self) -> bool:
        return not self.capped and not self.errors


def _query_can_reach_archive(values: PlanFilterValues) -> bool:
    """Return whether *values* permits archive rows."""
    return not values.kinds or any(
        kind.casefold() == "archive" for kind in values.kinds
    )


def make_deep_archive_request(
    snapshot: PlansSnapshot | None,
    *,
    project_scope: str | None,
    filter_session_open: bool,
    values: PlanFilterValues,
) -> DeepArchiveRequest | None:
    """Build a request token when the snapshot has a reachable coverage gap."""
    if (
        snapshot is None
        or snapshot.project != project_scope
        or not snapshot.archive_truncated
        or not _query_can_reach_archive(values)
        or (not filter_session_open and values.is_empty)
    ):
        return None
    project_roots = tuple(
        (project, plans_root)
        for project in snapshot.projects
        if (plans_root := snapshot.plans_roots.get(project)) is not None
    )
    if not project_roots:
        return None
    return DeepArchiveRequest(
        project_scope=project_scope,
        values=values,
        snapshot_identity=id(snapshot),
        project_roots=project_roots,
    )


def load_deep_archive_result(
    snapshot: PlansSnapshot,
    request: DeepArchiveRequest,
) -> DeepArchiveResult:
    """Browse and match one deep archive request on a worker thread."""
    fetched = load_deep_plan_archive(request.project_roots)
    records = build_plan_archive_filter_records(snapshot, fetched.archive)
    matcher = compile_plan_matcher(request.values)
    matching_archive = tuple(
        item
        for item, record in zip(fetched.archive, records, strict=True)
        if matcher(record)
    )
    return DeepArchiveResult(
        request=request,
        archive=matching_archive,
        scanned_count=fetched.scanned_count,
        capped=fetched.capped,
        errors=tuple(sorted(fetched.errors.items())),
    )


def merge_archive_matches(
    preview: tuple[ProjectArchive, ...],
    deep: tuple[ProjectArchive, ...],
) -> tuple[ProjectArchive, ...]:
    """Merge deep matches with preview rows by path in recency order."""
    by_path: dict[str, ProjectArchive] = {}
    for item in (*deep, *preview):
        by_path.setdefault(item.match.plan.path, item)
    return tuple(
        sorted(
            by_path.values(),
            key=lambda item: (
                item.match.plan.created_at,
                item.match.plan.path,
                item.project,
            ),
            reverse=True,
        )
    )


def deep_archive_coverage(
    snapshot: PlansSnapshot | None,
    values: PlanFilterValues,
    result: DeepArchiveResult | None,
) -> tuple[bool, str | None]:
    """Return exactness plus an optional honest coverage label."""
    if result is not None:
        if result.capped:
            return False, f"newest {DEEP_ARCHIVE_PER_PROJECT_LIMIT} searched"
        if result.errors:
            return False, "preview"
        return True, None
    if snapshot is None:
        return False, None
    exact = not (snapshot.archive_truncated and _query_can_reach_archive(values))
    return exact, None


def remember_deep_archive_result(
    cache: dict[DeepArchiveRequest, DeepArchiveResult],
    result: DeepArchiveResult,
) -> None:
    """Insert *result* into the bounded insertion-recency cache."""
    request = result.request
    cache.pop(request, None)
    cache[request] = result
    while len(cache) > DEEP_ARCHIVE_CACHE_LIMIT:
        cache.pop(next(iter(cache)), None)


__all__ = [
    "DEEP_ARCHIVE_DEBOUNCE_S",
    "DeepArchiveRequest",
    "DeepArchiveResult",
    "deep_archive_coverage",
    "load_deep_archive_result",
    "make_deep_archive_request",
    "merge_archive_matches",
    "remember_deep_archive_result",
]
