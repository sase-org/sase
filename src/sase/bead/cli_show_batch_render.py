"""Rendering for resolved ``sase bead show`` batches."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

from rich.cells import cell_len

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead._cli_show_batch_shared import (
    ShowBatch,
    ShowEntry,
    ShowRenderContext,
    ShowRenderContextResolver,
    render_context_key,
)
from sase.bead.cli_detail import render_issue_detail
from sase.bead.cli_detail_json import issue_detail_wire_dict
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.cli_query_render import render_list_compact
from sase.bead.cli_show_batch_context import default_show_render_context_resolver
from sase.markdown_width import markdown_print_width
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import (
    LinkAnchor,
    default_link_context,
    link_anchor_for_directory,
)
from sase.pager.known_kinds import known_kinds_from_artifact_context
from sase.pager.owner import document_owner_from_path


def render_show_batch(
    batch: ShowBatch,
    *,
    format_name: str,
    include_links: bool,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: ShowRenderContextResolver | None = None,
    images_mode: str = "never",
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
                images_mode=images_mode,
            )
        case _:
            raise AssertionError(f"unknown show format: {format_name}")


def build_show_batch_document(
    batch: ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: ShowRenderContextResolver | None = None,
    images_mode: str = "never",
) -> PagerDocument:
    """Build a pager document with one full-rendered section per bead."""
    render_context_for = render_context_for or default_show_render_context_resolver()
    sections = _show_batch_sections(
        batch,
        style=style,
        wrap=wrap,
        render_context_for=render_context_for,
        images_mode=images_mode,
    )
    return PagerDocument(
        sections=sections,
        title=_show_batch_document_title(batch),
        origin=PagerOrigin.BEAD,
        link_context=default_link_context(),
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
    batch: ShowBatch,
    *,
    include_links: bool,
    render_context_for: ShowRenderContextResolver,
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
                plan_roots=context.plan_roots,
                design_cwd=context.design_cwd,
            )
        )
    payload: object = envelopes if batch.multi_requested else envelopes[0]
    return json.dumps(payload, indent=2) + "\n"


def _render_full_batch(
    batch: ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: ShowRenderContextResolver,
    images_mode: str = "never",
) -> str:
    document = build_show_batch_document(
        batch,
        style=style,
        wrap=wrap,
        render_context_for=render_context_for,
        images_mode=images_mode,
    )
    return render_show_document(document, style=style, wrap=wrap)


def _show_batch_sections(
    batch: ShowBatch,
    *,
    style: DetailStyle,
    wrap: int | None,
    render_context_for: ShowRenderContextResolver,
    images_mode: str = "never",
) -> tuple[PagerSection, ...]:
    from sase.pager.bead_prefixes import pager_bead_id_prefixes
    from sase.pager.link_scan import normalize_bead_id_prefixes

    enabled_prefixes = pager_bead_id_prefixes((), include_enabled_projects=True)
    reference_contexts: dict[object, ArtifactRefContext | None] = {}

    def context_for(
        entry: ShowEntry, render_context: ShowRenderContext
    ) -> ArtifactRefContext | None:
        key = render_context_key(entry.origin)
        if key not in reference_contexts:
            reference_contexts[key] = render_context.reference_context_factory()
        return reference_contexts[key]

    sections: list[PagerSection] = []
    for entry in batch.entries:
        issue = entry.issue
        context = render_context_for(entry.origin)
        subject_ref = f"bead:{issue.id}"
        reference_context = context_for(entry, context)
        bead_ids = [issue.id]
        detail = entry.detail
        if detail is not None:
            for group in (
                detail.ancestors,
                detail.phases,
                detail.child_epics,
                detail.depends_on,
                detail.blocks,
            ):
                bead_ids.extend(ref.issue_id for ref in group)
        id_prefixes = pager_bead_id_prefixes(bead_ids, include_enabled_projects=False)
        bead_id_prefixes = normalize_bead_id_prefixes((*id_prefixes, *enabled_prefixes))
        body = render_issue_detail(
            _require_detail(entry),
            relativize_design=context.relativize_design,
            plan_roots=context.plan_roots,
            design_cwd=context.design_cwd,
            reference_context=reference_context,
            creator_url=(
                context.creator_url_for(issue.created_by) if issue.created_by else None
            ),
            page_url=context.page_url_for(issue.id),
            project_label=(
                entry.origin.project_label if entry.origin is not None else None
            ),
            style=style,
            wrap=wrap,
            images_mode=images_mode,
        )
        section = PagerSection(
            identity=subject_ref,
            title=f"{issue.id} · {issue.title}",
            kind="bead",
            body=body,
            subject_ref=subject_ref,
            link_anchors=_show_entry_link_anchors(context),
            origin=PagerOrigin.BEAD,
            owner=document_owner_from_path(
                context.design_cwd, source_reference=subject_ref
            ),
            known_kinds=known_kinds_from_artifact_context(reference_context),
            bead_id_prefixes=bead_id_prefixes,
        )
        try:
            from sase.bead.show_images import (
                attachment_names_for_issue,
                attachment_targets_for_body,
            )

            names = attachment_names_for_issue(issue)
            if names:
                targets = attachment_targets_for_body(
                    issue.id, section.plain_text, names
                )  # type: ignore[assignment]
                if targets:
                    section = replace(section, targets=targets)  # type: ignore[arg-type]
        except Exception:
            pass
        sections.append(section)
    return tuple(sections)


def _show_entry_link_anchors(
    context: ShowRenderContext,
) -> tuple[LinkAnchor, ...]:
    anchor = link_anchor_for_directory(context.design_cwd, workspace_num=1)
    if anchor is None:
        return ()
    return (anchor,)


def _show_batch_document_title(batch: ShowBatch) -> str:
    if len(batch.entries) == 1:
        issue = batch.entries[0].issue
        return f"{issue.id} · {issue.title}"
    return f"{len(batch.entries)} beads"


def _require_detail(entry: ShowEntry) -> IssueDetail:
    detail = entry.detail
    if detail is None:
        raise AssertionError("show detail required for this format")
    return detail


__all__ = [
    "build_show_batch_document",
    "render_show_batch",
    "render_show_document",
]
