"""Batch resolution and rendering for ``sase bead show``."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.cells import cell_len

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail import render_issue_detail, resolve_issue_detail
from sase.bead.cli_detail_json import issue_detail_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.cli_query_render import render_list_compact
from sase.bead.model import Issue
from sase.markdown_width import markdown_print_width


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

    for requested_id in ids:
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
        multi_requested=len(ids) > 1,
    )


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

    blocks = [
        render_issue_detail(
            _require_detail(entry),
            relativize_design=relativize_design,
            plan_roots=plan_roots,
            reference_context=context_for(entry.issue),
            creator_url=(
                creator_url_for(entry.issue.created_by)
                if entry.issue.created_by
                else None
            ),
            page_url=page_url_for(entry.issue.id),
            style=style,
            wrap=wrap,
        )
        for entry in batch.entries
    ]
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


def _require_detail(entry: _ShowEntry) -> IssueDetail:
    detail = entry.detail
    if detail is None:
        raise AssertionError("show detail required for this format")
    return detail


__all__ = [
    "render_show_batch",
    "resolve_show_batch",
]
