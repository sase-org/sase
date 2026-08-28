"""Batch resolution and rendering for ``sase bead show``."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rich.cells import cell_len

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail import render_issue_detail, resolve_issue_detail
from sase.bead.cli_detail_context import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    resolve_bead_creator_url,
    resolve_bead_page_url,
)
from sase.bead.cli_detail_json import issue_detail_wire_dict
from sase.bead.cli_detail_links import assemble_bead_link_neighborhood
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.cli_query_render import render_list_compact
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
from sase.markdown_width import markdown_print_width
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

if TYPE_CHECKING:
    from sase.bead.cross_project import BeadStoreOrigin

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ShowFailure:
    """One requested bead ID that could not be resolved."""

    requested_id: str
    message: str


@dataclass(frozen=True)
class _ShowEntry:
    """One resolved bead in argv order."""

    requested_id: str
    issue: Issue
    detail: IssueDetail | None
    origin: BeadStoreOrigin | None


@dataclass(frozen=True)
class _ShowBatch:
    """Resolved ``sase bead show`` batch plus ordered failures."""

    entries: tuple[_ShowEntry, ...]
    failures: tuple[_ShowFailure, ...]
    multi_requested: bool


@dataclass(frozen=True)
class _ShowRequest:
    """One requested ID, optionally pinned to an already-routed store."""

    requested_id: str
    store: RoutedShowStore | None = None


DetailEnricher = Callable[[IssueDetail], IssueDetail]
ReferenceContextFactory = Callable[[], ArtifactRefContext | None]
CreatorUrlResolver = Callable[[str], str | None]
PageUrlResolver = Callable[[str], str | None]
_ShowRenderContextResolver = Callable[["BeadStoreOrigin | None"], "_ShowRenderContext"]


@dataclass(frozen=True)
class _ShowRenderContext:
    """Workspace-derived presentation context for one show entry origin."""

    relativize_design: bool
    plan_roots: tuple[Path, ...]
    design_cwd: Path | None
    reference_context_factory: ReferenceContextFactory
    creator_url_for: CreatorUrlResolver
    page_url_for: PageUrlResolver


#: What `assemble_bead_link_neighborhood` raises when the artifact-link store
#: cannot be read. Each caller decides whether to report it or degrade.
ARTIFACT_LINK_NEIGHBORHOOD_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
)


def artifact_link_neighborhood_detail(detail: IssueDetail) -> IssueDetail:
    """Return *detail* with its typed artifact-link neighborhood attached."""
    return replace(
        detail,
        artifact_links=assemble_bead_link_neighborhood(
            bead_id=detail.issue.id,
            bead_owned_rows=detail.bead_owned_artifact_links,
            fallback_issue=detail.issue,
        ),
    )


def enrich_with_artifact_link_neighborhood(detail: IssueDetail) -> IssueDetail:
    """Attach the link neighborhood, or leave *detail* unchanged on failure.

    `sase bead show` reports the failure and exits, which a host that is not a
    CLI entry point must never do — the pager resolves `bead:` links from
    inside a keypress handler. Degrading here costs that document its LINKS
    section rather than the whole document.
    """
    try:
        return artifact_link_neighborhood_detail(detail)
    except ARTIFACT_LINK_NEIGHBORHOOD_ERRORS:
        log.warning(
            "could not assemble the artifact-link neighborhood for %s",
            detail.issue.id,
            exc_info=True,
        )
        return detail


def resolve_show_batch(
    view: Any,
    ids: Sequence[str],
    *,
    format_name: str,
    include_links: bool,
    detail_enricher: DetailEnricher | None = None,
    project_ref: str | None = None,
    router: ShowStoreRouter | None = None,
) -> _ShowBatch:
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
) -> _ShowBatch:
    """Resolve requested IDs through an already-owned store router."""
    entries: list[_ShowEntry] = []
    failures: list[_ShowFailure] = []
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
                _ShowFailure(requested_id, f"issue not found: {requested_id}")
            )
            continue
        except ShowStoreRoutingError as exc:
            failures.append(_ShowFailure(requested_id, str(exc)))
            continue
        except ValueError as exc:
            failures.append(_ShowFailure(requested_id, str(exc)))
            continue

        if issue.id in emitted:
            continue
        emitted.add(issue.id)

        if detail is not None and detail_enricher is not None:
            detail = detail_enricher(detail)
        entries.append(_ShowEntry(requested_id, issue, detail, origin))

    return _ShowBatch(
        entries=tuple(entries),
        failures=tuple(failures),
        multi_requested=len(expanded_ids) > 1 or expanded_any,
    )


def _expand_show_ids(
    router: ShowStoreRouter,
    ids: Sequence[str],
    failures: list[_ShowFailure],
) -> tuple[list[_ShowRequest], bool]:
    """Expand ``<epic-id>..`` tokens in argv order, appending failures in place."""
    expanded_ids: list[_ShowRequest] = []
    expanded_any = False

    for token in ids:
        try:
            stem = expansion_stem(token)
        except ExpansionError as exc:
            failures.append(_ShowFailure(token, str(exc)))
            continue

        if stem is None:
            expanded_ids.append(_ShowRequest(token))
            continue

        expanded_any = True
        try:
            routed, issue = _resolve_existing_issue_store(router, stem)
            expanded_ids.extend(
                _ShowRequest(expanded_id, routed)
                for expanded_id in expand_epic_target(routed.view, issue.id)
            )
        except KeyError:
            failures.append(_ShowFailure(stem, f"issue not found: {stem}"))
        except ShowStoreRoutingError as exc:
            failures.append(_ShowFailure(stem, str(exc)))
        except ValueError as exc:
            failures.append(_ShowFailure(stem, str(exc)))

    return expanded_ids, expanded_any


def _resolve_existing_issue_store(
    router: ShowStoreRouter,
    requested_id: str,
) -> tuple[RoutedShowStore, Issue]:
    primary = router.primary_store()
    try:
        return primary, primary.view.show(requested_id)
    except KeyError:
        if router.is_project_pinned:
            raise
        foreign = router.foreign_store_for_bead_id(requested_id)
        if foreign is None:
            raise
        return foreign, foreign.view.show(requested_id)


def _resolve_show_request(
    router: ShowStoreRouter,
    request: _ShowRequest,
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

    primary = router.primary_store()
    try:
        return _resolve_in_store(
            primary,
            request.requested_id,
            format_name=format_name,
            include_links=include_links,
        )
    except KeyError:
        if router.is_project_pinned:
            raise
        foreign = router.foreign_store_for_bead_id(request.requested_id)
        if foreign is None:
            raise
        return _resolve_in_store(
            foreign,
            request.requested_id,
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


def default_show_render_context_resolver(
    *,
    design_paths_are_relative_fn: Callable[..., bool] | None = None,
    plan_reference_roots_fn: Callable[..., tuple[Path, ...]] | None = None,
    artifact_reference_context_fn: Callable[..., ArtifactRefContext | None]
    | None = None,
    resolve_bead_creator_url_fn: Callable[..., str | None] | None = None,
    resolve_bead_page_url_fn: Callable[..., str | None] | None = None,
) -> _ShowRenderContextResolver:
    """Return a memoizing resolver for workspace-derived show render context."""
    design_fn = design_paths_are_relative_fn or design_paths_are_relative
    plan_roots_fn = plan_reference_roots_fn or plan_reference_roots
    reference_fn = artifact_reference_context_fn or artifact_reference_context
    creator_url_fn = resolve_bead_creator_url_fn or resolve_bead_creator_url
    page_url_fn = resolve_bead_page_url_fn or resolve_bead_page_url
    cache: dict[object, _ShowRenderContext] = {}

    def resolve(origin: BeadStoreOrigin | None) -> _ShowRenderContext:
        key = _render_context_key(origin)
        if key not in cache:
            workspace = origin.primary_workspace if origin is not None else None
            cache[key] = _ShowRenderContext(
                relativize_design=_call_workspace_fn(design_fn, workspace),
                plan_roots=_call_workspace_fn(plan_roots_fn, workspace),
                design_cwd=workspace,
                reference_context_factory=_reference_context_factory(
                    reference_fn,
                    workspace,
                ),
                creator_url_for=_creator_url_resolver(creator_url_fn, workspace),
                page_url_for=_page_url_resolver(page_url_fn, workspace),
            )
        return cache[key]

    return resolve


def _render_context_key(origin: BeadStoreOrigin | None) -> object:
    if origin is None:
        return None
    return (origin.project_key, origin.primary_workspace)


def _call_workspace_fn(function: Callable[..., Any], workspace: Path | None) -> Any:
    if workspace is None:
        return function()
    try:
        return function(workspace)
    except TypeError:
        return function()


def _reference_context_factory(
    function: Callable[..., ArtifactRefContext | None],
    workspace: Path | None,
) -> ReferenceContextFactory:
    def factory() -> ArtifactRefContext | None:
        return _call_workspace_fn(function, workspace)

    return factory


def _creator_url_resolver(
    function: Callable[..., str | None],
    workspace: Path | None,
) -> CreatorUrlResolver:
    def resolve(created_by: str) -> str | None:
        if workspace is None:
            return function(created_by)
        try:
            return function(created_by, workspace)
        except TypeError:
            return function(created_by)

    return resolve


def _page_url_resolver(
    function: Callable[..., str | None],
    workspace: Path | None,
) -> PageUrlResolver:
    def resolve(bead_id: str) -> str | None:
        if workspace is None:
            return function(bead_id)
        try:
            return function(bead_id, workspace)
        except TypeError:
            return function(bead_id)

    return resolve


def render_show_batch(
    batch: _ShowBatch,
    *,
    format_name: str,
    include_links: bool,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: _ShowRenderContextResolver | None = None,
) -> str:
    """Render one resolved show batch in the requested format."""
    if not batch.entries:
        return ""
    render_context_for = render_context_for or default_show_render_context_resolver()

    match format_name:
        case "compact":
            return render_list_compact(
                [entry.issue for entry in batch.entries],
                use_color=style is not DetailStyle.PLAIN,
            )
        case "json":
            return _render_json_batch(
                batch,
                include_links=include_links,
                render_context_for=render_context_for,
            )
        case "full":
            return _render_full_batch(
                batch,
                style=style,
                wrap=wrap,
                render_context_for=render_context_for,
            )
        case _:
            raise AssertionError(f"unknown show format: {format_name}")


def build_show_batch_document(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: _ShowRenderContextResolver | None = None,
) -> PagerDocument:
    """Build a pager document with one full-rendered section per bead."""
    render_context_for = render_context_for or default_show_render_context_resolver()
    sections = _show_batch_sections(
        batch,
        style=style,
        wrap=wrap,
        render_context_for=render_context_for,
    )
    return PagerDocument(
        sections=sections,
        title=_show_batch_document_title(batch),
        origin=PagerOrigin.BEAD,
    )


def render_show_document(
    document: PagerDocument,
    *,
    style: DetailStyle,
    wrap: int | None,
) -> str:
    """Render a bead-show pager document to today's CLI string format."""
    blocks = [cast(str, section.body) for section in document.sections]
    if not blocks:
        return ""
    if len(blocks) == 1:
        return blocks[0]

    palette = DetailPalette.for_style(style)
    divider_width = wrap if wrap is not None else markdown_print_width()
    sections = [
        f"{_show_divider(index, len(blocks), palette=palette, width=divider_width)}\n"
        f"{block.rstrip(chr(10))}"
        for index, block in enumerate(blocks, start=1)
    ]
    return "\n\n".join(sections) + "\n"


def _show_divider(
    index: int,
    total: int,
    *,
    palette: DetailPalette,
    width: int,
) -> str:
    """Return a left-anchored ordinal divider for a multi-bead full render."""
    marker = f"{index}/{total}"
    prefix = f"── {marker} "
    fill = "─" * max(width - cell_len(prefix), 0)
    return (
        f"{palette.separator('── ')}"
        f"{palette.section(marker)}"
        f"{palette.separator(f' {fill}')}"
    )


def _render_json_batch(
    batch: _ShowBatch,
    *,
    include_links: bool,
    render_context_for: _ShowRenderContextResolver,
) -> str:
    envelopes = []
    for entry in batch.entries:
        context = render_context_for(entry.origin)
        envelopes.append(
            issue_detail_wire_dict(
                _require_detail(entry),
                created_by_url=(
                    context.creator_url_for(entry.issue.created_by)
                    if entry.issue.created_by
                    else None
                ),
                page_url=context.page_url_for(entry.issue.id),
                include_links=include_links,
            )
        )
    payload: object = envelopes if batch.multi_requested else envelopes[0]
    return json.dumps(payload, indent=2) + "\n"


def _render_full_batch(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: _ShowRenderContextResolver,
) -> str:
    document = build_show_batch_document(
        batch,
        style=style,
        wrap=wrap,
        render_context_for=render_context_for,
    )
    return render_show_document(document, style=style, wrap=wrap)


def _show_batch_sections(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: _ShowRenderContextResolver,
) -> tuple[PagerSection, ...]:
    reference_contexts: dict[object, ArtifactRefContext | None] = {}

    def context_for(
        entry: _ShowEntry, render_context: _ShowRenderContext
    ) -> ArtifactRefContext | None:
        issue = entry.issue
        if not issue.refs:
            return None
        key = _render_context_key(entry.origin)
        if key not in reference_contexts:
            reference_contexts[key] = render_context.reference_context_factory()
        return reference_contexts[key]

    sections: list[PagerSection] = []
    for entry in batch.entries:
        issue = entry.issue
        context = render_context_for(entry.origin)
        subject_ref = f"bead:{issue.id}"
        sections.append(
            PagerSection(
                identity=subject_ref,
                title=f"{issue.id} · {issue.title}",
                kind="bead",
                body=render_issue_detail(
                    _require_detail(entry),
                    relativize_design=context.relativize_design,
                    plan_roots=context.plan_roots,
                    design_cwd=context.design_cwd,
                    reference_context=context_for(entry, context),
                    creator_url=(
                        context.creator_url_for(issue.created_by)
                        if issue.created_by
                        else None
                    ),
                    page_url=context.page_url_for(issue.id),
                    project_label=(
                        entry.origin.project_label if entry.origin is not None else None
                    ),
                    style=style,
                    wrap=wrap,
                ),
                subject_ref=subject_ref,
            )
        )
    return tuple(sections)


def _show_batch_document_title(batch: _ShowBatch) -> str:
    if len(batch.entries) == 1:
        issue = batch.entries[0].issue
        return f"{issue.id} · {issue.title}"
    return f"{len(batch.entries)} beads"


def _require_detail(entry: _ShowEntry) -> IssueDetail:
    detail = entry.detail
    if detail is None:
        raise AssertionError("show detail required for this format")
    return detail


__all__ = [
    "ARTIFACT_LINK_NEIGHBORHOOD_ERRORS",
    "artifact_link_neighborhood_detail",
    "build_show_batch_document",
    "default_show_render_context_resolver",
    "enrich_with_artifact_link_neighborhood",
    "render_show_batch",
    "render_show_document",
    "resolve_show_batch",
]
