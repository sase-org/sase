"""Batch resolution for ``sase bead show``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sase.bead._cli_show_batch_shared import (
    DetailEnricher,
    ShowBatch,
    ShowEntry,
    ShowFailure,
    ShowRequest,
)
from sase.bead.cli_detail import resolve_issue_detail
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_show_router import (
    RoutedShowStore,
    ShowStoreRouter,
    ShowStoreRoutingError,
)
from sase.bead.model import Issue
from sase.bead.show_epic_expansion import (
    ExpansionError,
    expand_epic_target,
    expansion_stem,
)

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin


def resolve_show_batch(
    view: Any | None,
    ids: Sequence[str],
    *,
    format_name: str,
    include_links: bool,
    detail_enricher: DetailEnricher | None = None,
    project_ref: str | None = None,
    router: ShowStoreRouter | None = None,
) -> ShowBatch:
    """Resolve requested IDs, preserving argv order and de-duping by canonical ID."""
    if router is None:
        with ShowStoreRouter(view, project_ref=project_ref) as owned_router:
            return _resolve_show_batch(
                owned_router,
                ids,
                format_name=format_name,
                include_links=include_links,
                detail_enricher=detail_enricher,
            )
    return _resolve_show_batch(
        router,
        ids,
        format_name=format_name,
        include_links=include_links,
        detail_enricher=detail_enricher,
    )


def _resolve_show_batch(
    router: ShowStoreRouter,
    ids: Sequence[str],
    *,
    format_name: str,
    include_links: bool,
    detail_enricher: DetailEnricher | None,
) -> ShowBatch:
    """Resolve requested IDs through an already-owned store router."""
    entries: list[ShowEntry] = []
    failures: list[ShowFailure] = []
    emitted: set[str] = set()

    if router.is_project_pinned:
        router.primary_store()

    expanded_ids, expanded_any = _expand_show_ids(router, ids, failures)

    for request in expanded_ids:
        requested_id = request.requested_id
        try:
            issue, detail, origin = _resolve_show_request(
                router,
                request,
                format_name=format_name,
                include_links=include_links,
            )
        except KeyError:
            failures.append(
                ShowFailure(requested_id, f"issue not found: {requested_id}")
            )
            continue
        except ShowStoreRoutingError as exc:
            failures.append(ShowFailure(requested_id, str(exc)))
            continue
        except ValueError as exc:
            failures.append(ShowFailure(requested_id, str(exc)))
            continue

        if issue.id in emitted:
            continue
        emitted.add(issue.id)

        if detail is not None and detail_enricher is not None:
            detail = detail_enricher(detail)
        entries.append(ShowEntry(requested_id, issue, detail, origin))

    return ShowBatch(
        entries=tuple(entries),
        failures=tuple(failures),
        multi_requested=len(expanded_ids) > 1 or expanded_any,
    )


def _expand_show_ids(
    router: ShowStoreRouter,
    ids: Sequence[str],
    failures: list[ShowFailure],
) -> tuple[list[ShowRequest], bool]:
    """Expand ``<epic-id>..`` tokens in argv order, appending failures in place."""
    expanded_ids: list[ShowRequest] = []
    expanded_any = False

    for token in ids:
        try:
            stem = expansion_stem(token)
        except ExpansionError as exc:
            failures.append(ShowFailure(token, str(exc)))
            continue

        if stem is None:
            expanded_ids.append(ShowRequest(token))
            continue

        expanded_any = True
        try:
            routed, issue = _resolve_existing_issue_store(router, stem)
            expanded_ids.extend(
                ShowRequest(expanded_id, routed)
                for expanded_id in expand_epic_target(routed.view, issue.id)
            )
        except KeyError:
            failures.append(ShowFailure(stem, f"issue not found: {stem}"))
        except ShowStoreRoutingError as exc:
            failures.append(ShowFailure(stem, str(exc)))
        except ValueError as exc:
            failures.append(ShowFailure(stem, str(exc)))

    return expanded_ids, expanded_any


def _resolve_existing_issue_store(
    router: ShowStoreRouter,
    requested_id: str,
) -> tuple[RoutedShowStore, Issue]:
    routed = router.route_target(requested_id)
    try:
        return routed.store, routed.store.view.show(routed.resolved_id)
    except KeyError as local_miss:
        if router.is_project_pinned or routed.store.origin is not None:
            raise
        try:
            routed = router.foreign_target_for_bead_id(requested_id)
        except KeyError:
            raise local_miss from None
        return routed.store, routed.store.view.show(routed.resolved_id)


def _resolve_show_request(
    router: ShowStoreRouter,
    request: ShowRequest,
    *,
    format_name: str,
    include_links: bool,
) -> tuple[Issue, IssueDetail | None, BeadStoreOrigin | None]:
    if request.store is not None:
        return _resolve_in_store(
            request.store,
            request.requested_id,
            format_name=format_name,
            include_links=include_links,
        )

    routed = router.route_target(request.requested_id)
    try:
        return _resolve_in_store(
            routed.store,
            routed.resolved_id,
            format_name=format_name,
            include_links=include_links,
        )
    except KeyError as local_miss:
        if router.is_project_pinned or routed.store.origin is not None:
            raise
        try:
            routed = router.foreign_target_for_bead_id(request.requested_id)
        except KeyError:
            raise local_miss from None
        return _resolve_in_store(
            routed.store,
            routed.resolved_id,
            format_name=format_name,
            include_links=include_links,
        )


def _resolve_in_store(
    store: RoutedShowStore,
    requested_id: str,
    *,
    format_name: str,
    include_links: bool,
) -> tuple[Issue, IssueDetail | None, BeadStoreOrigin | None]:
    if format_name == "compact":
        return store.view.show(requested_id), None, store.origin
    detail = resolve_issue_detail(
        store.view,
        requested_id,
        include_links=include_links,
    )
    return detail.issue, detail, store.origin


__all__ = [
    "resolve_show_batch",
]
