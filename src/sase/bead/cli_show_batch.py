"""Batch resolution and rendering for ``sase bead show``."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from rich.cells import cell_len

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail import render_issue_detail, resolve_issue_detail
from sase.bead.cli_detail_json import issue_detail_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.cli_query_render import render_list_compact
from sase.bead.model import Issue
from sase.bead.show_epic_expansion import (
    ExpansionError,
    expand_epic_target,
    expansion_stem,
)
from sase.markdown_width import markdown_print_width
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


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


@dataclass(frozen=True)
class _ShowBatch:
    """Resolved ``sase bead show`` batch plus ordered failures."""

    entries: tuple[_ShowEntry, ...]
    failures: tuple[_ShowFailure, ...]
    multi_requested: bool


DetailEnricher = Callable[[IssueDetail], IssueDetail]
ReferenceContextFactory = Callable[[], ArtifactRefContext | None]
CreatorUrlResolver = Callable[[str], str | None]
PageUrlResolver = Callable[[str], str | None]


def resolve_show_batch(
    view: Any,
    ids: Sequence[str],
    *,
    format_name: str,
    include_links: bool,
    detail_enricher: DetailEnricher | None = None,
) -> _ShowBatch:
    """Resolve requested IDs, preserving argv order and de-duping by canonical ID."""
    entries: list[_ShowEntry] = []
    failures: list[_ShowFailure] = []
    emitted: set[str] = set()

    expanded_ids, expanded_any = _expand_show_ids(view, ids, failures)

    for requested_id in expanded_ids:
        try:
            if format_name == "compact":
                issue = view.show(requested_id)
                detail = None
            else:
                detail = resolve_issue_detail(
                    view,
                    requested_id,
                    include_links=include_links,
                )
                issue = detail.issue
        except KeyError:
            failures.append(
                _ShowFailure(requested_id, f"issue not found: {requested_id}")
            )
            continue
        except ValueError as exc:
            failures.append(_ShowFailure(requested_id, str(exc)))
            continue

        if issue.id in emitted:
            continue
        emitted.add(issue.id)

        if detail is not None and detail_enricher is not None:
            detail = detail_enricher(detail)
        entries.append(_ShowEntry(requested_id, issue, detail))

    return _ShowBatch(
        entries=tuple(entries),
        failures=tuple(failures),
        multi_requested=len(expanded_ids) > 1 or expanded_any,
    )


def _expand_show_ids(
    view: Any,
    ids: Sequence[str],
    failures: list[_ShowFailure],
) -> tuple[list[str], bool]:
    """Expand ``<epic-id>..`` tokens in argv order, appending failures in place."""
    expanded_ids: list[str] = []
    expanded_any = False

    for token in ids:
        try:
            stem = expansion_stem(token)
        except ExpansionError as exc:
            failures.append(_ShowFailure(token, str(exc)))
            continue

        if stem is None:
            expanded_ids.append(token)
            continue

        expanded_any = True
        try:
            expanded_ids.extend(expand_epic_target(view, stem))
        except KeyError:
            failures.append(_ShowFailure(stem, f"issue not found: {stem}"))

    return expanded_ids, expanded_any


def render_show_batch(
    batch: _ShowBatch,
    *,
    format_name: str,
    include_links: bool,
    style: DetailStyle,
    wrap: int | None,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context_factory: ReferenceContextFactory,
    creator_url_for: CreatorUrlResolver,
    page_url_for: PageUrlResolver,
) -> str:
    """Render one resolved show batch in the requested format."""
    if not batch.entries:
        return ""

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
                creator_url_for=creator_url_for,
                page_url_for=page_url_for,
            )
        case "full":
            return _render_full_batch(
                batch,
                style=style,
                wrap=wrap,
                relativize_design=relativize_design,
                plan_roots=plan_roots,
                reference_context_factory=reference_context_factory,
                creator_url_for=creator_url_for,
                page_url_for=page_url_for,
            )
        case _:
            raise AssertionError(f"unknown show format: {format_name}")


def build_show_batch_document(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context_factory: ReferenceContextFactory,
    creator_url_for: CreatorUrlResolver,
    page_url_for: PageUrlResolver,
) -> PagerDocument:
    """Build a pager document with one full-rendered section per bead."""
    sections = _show_batch_sections(
        batch,
        style=style,
        wrap=wrap,
        relativize_design=relativize_design,
        plan_roots=plan_roots,
        reference_context_factory=reference_context_factory,
        creator_url_for=creator_url_for,
        page_url_for=page_url_for,
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
    creator_url_for: CreatorUrlResolver,
    page_url_for: PageUrlResolver,
) -> str:
    envelopes = [
        issue_detail_wire_dict(
            _require_detail(entry),
            created_by_url=(
                creator_url_for(entry.issue.created_by)
                if entry.issue.created_by
                else None
            ),
            page_url=page_url_for(entry.issue.id),
            include_links=include_links,
        )
        for entry in batch.entries
    ]
    payload: object = envelopes if batch.multi_requested else envelopes[0]
    return json.dumps(payload, indent=2) + "\n"


def _render_full_batch(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context_factory: ReferenceContextFactory,
    creator_url_for: CreatorUrlResolver,
    page_url_for: PageUrlResolver,
) -> str:
    document = build_show_batch_document(
        batch,
        style=style,
        wrap=wrap,
        relativize_design=relativize_design,
        plan_roots=plan_roots,
        reference_context_factory=reference_context_factory,
        creator_url_for=creator_url_for,
        page_url_for=page_url_for,
    )
    return render_show_document(document, style=style, wrap=wrap)


def _show_batch_sections(
    batch: _ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    relativize_design: bool,
    plan_roots: tuple[Path, ...],
    reference_context_factory: ReferenceContextFactory,
    creator_url_for: CreatorUrlResolver,
    page_url_for: PageUrlResolver,
) -> tuple[PagerSection, ...]:
    reference_context: ArtifactRefContext | None = None
    reference_context_resolved = False

    def context_for(issue: Issue) -> ArtifactRefContext | None:
        nonlocal reference_context, reference_context_resolved
        if not issue.refs:
            return None
        if not reference_context_resolved:
            reference_context = reference_context_factory()
            reference_context_resolved = True
        return reference_context

    sections: list[PagerSection] = []
    for entry in batch.entries:
        issue = entry.issue
        subject_ref = f"bead:{issue.id}"
        sections.append(
            PagerSection(
                identity=subject_ref,
                title=f"{issue.id} · {issue.title}",
                kind="bead",
                body=render_issue_detail(
                    _require_detail(entry),
                    relativize_design=relativize_design,
                    plan_roots=plan_roots,
                    reference_context=context_for(issue),
                    creator_url=(
                        creator_url_for(issue.created_by) if issue.created_by else None
                    ),
                    page_url=page_url_for(issue.id),
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
    "build_show_batch_document",
    "render_show_batch",
    "render_show_document",
    "resolve_show_batch",
]
