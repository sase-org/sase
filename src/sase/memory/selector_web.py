"""Memory-web and strand resolution helpers for selector batches."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from sase.core.glossary_facade import GlossarySpanKind
from sase.memory.link_resolve import (
    MemoryLinkTarget,
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    resolve_memory_link_target,
)
from sase.memory.links import MemoryLink, scan_memory_links
from sase.memory.notes import MemoryNote
from sase.memory.render import ResolvedMemoryNote
from sase.memory.selector_models import (
    MemorySelectorError,
    MemoryWebReadLink,
    NoteInlineContext,
    NoteSelector,
    PendingNoteStrandRoot,
    ResolvedStrandLink,
    StrandSelector,
    WebSelector,
    MemoryWebReadNode,
    MemoryWebReadSection,
    always_reference_target,
    link_target_key,
)
from sase.memory.selector_notes import (
    note_target_keys,
    note_tree_keys,
    resolve_extra_note,
)
from sase.memory.web import (
    MemoryStrand,
    MemoryWebLookupError,
    ScopedMemoryWeb,
    StrandLinkSpan,
    WebStrandOrigin,
    resolve_memory_strand,
    resolve_strand_closure,
)
from sase.memory.web.resolution import GlossaryClosureNode

_EXTRA_ROOT_DEPTH = 0


def resolve_web_sections(
    classified: list[NoteSelector | WebSelector | StrandSelector],
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    depth: int | None,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    note_inline_context: NoteInlineContext,
    rendered_note_keys: frozenset[str] = frozenset(),
) -> tuple[tuple[MemoryWebReadSection, ...], tuple[ResolvedMemoryNote, ...]]:
    """Resolve requested web/strand selectors and their authored link roots."""
    web_items = [
        item for item in classified if isinstance(item, (WebSelector, StrandSelector))
    ]
    if not web_items:
        return (), ()
    by_slug = {scoped.slug: scoped for scoped in scoped_webs}
    order: list[str] = []
    requested_slugs: dict[str, set[str]] = {}
    for item in web_items:
        scoped = by_slug.get(item.web_slug)
        if scoped is None:
            raise MemorySelectorError(f"unknown memory web: {item.web_slug}")
        if item.web_slug not in requested_slugs:
            requested_slugs[item.web_slug] = set()
            order.append(item.web_slug)
        if isinstance(item, WebSelector):
            requested_slugs[item.web_slug].update(
                strand.slug for strand in scoped.strands
            )
            continue
        try:
            strand = resolve_memory_strand(
                replace(scoped.web, strands=scoped.strands), item.keyword
            )
        except MemoryWebLookupError as exc:
            raise MemorySelectorError(str(exc)) from exc
        requested_slugs[item.web_slug].add(strand.slug)

    sections: list[MemoryWebReadSection] = []
    cross_web_pending: list[
        tuple[MemoryStrand, MemoryStrandLinkTarget, MemoryLink]
    ] = []
    cross_note_pending: list[MemoryNoteLinkTarget] = []
    for slug in order:
        scoped = by_slug[slug]
        merged_web = replace(scoped.web, strands=scoped.strands)
        roots = tuple(
            strand for strand in scoped.strands if strand.slug in requested_slugs[slug]
        )
        link_edges = _resolve_strand_links(
            scoped.strands, notes=notes, scoped_webs=scoped_webs, depth=depth
        )
        same_web_spans = tuple(
            StrandLinkSpan(
                edge.strand.slug, edge.target.strand.slug, edge.link.raw, edge.link.span
            )
            for edge in link_edges
            if edge.inline
            and isinstance(edge.target, MemoryStrandLinkTarget)
            and edge.target.web.slug == slug
        )
        closure, strand_by_index = resolve_strand_closure(
            merged_web, scoped.strands, roots, depth=depth, link_spans=same_web_spans
        )
        rendered_slugs = {
            strand_by_index[node.entry.index].slug for node in closure.nodes
        }
        node_links: dict[str, list[MemoryWebReadLink]] = {}
        resolved_links: list[MemoryLinkTarget] = []
        seen_link_keys: set[str] = set()
        for edge in link_edges:
            if edge.strand.slug not in rendered_slugs:
                continue
            node_links.setdefault(edge.strand.slug, []).append(
                MemoryWebReadLink(edge.target, "inline" if edge.inline else "reference")
            )
            if isinstance(edge.target, MemoryStrandLinkTarget):
                if (
                    edge.target.web.slug == slug
                    and edge.target.strand.slug in rendered_slugs
                ):
                    continue
                if edge.inline and edge.target.web.slug != slug:
                    cross_web_pending.append((edge.strand, edge.target, edge.link))
                    continue
            elif edge.inline and isinstance(edge.target, MemoryNoteLinkTarget):
                cross_note_pending.append(edge.target)
                continue
            key = link_target_key(edge.target)
            if key not in seen_link_keys:
                seen_link_keys.add(key)
                resolved_links.append(edge.target)
        sections.append(
            MemoryWebReadSection(
                web=merged_web,
                nodes=tuple(
                    _closure_node(
                        node,
                        strand_by_index,
                        scoped.origins,
                        links=tuple(
                            node_links.get(strand_by_index[node.entry.index].slug, ())
                        ),
                    )
                    for node in closure.nodes
                ),
                depth_limit=closure.depth_limit,
                truncated=closure.truncated,
                resolved_links=tuple(resolved_links),
            )
        )

    for source, target, link in cross_web_pending:
        _apply_cross_web_root(sections, by_slug, source, target, link)
    extra_notes = _resolve_cross_note_roots(
        cross_note_pending,
        project_root=project_root,
        home_root=home_root,
        project_name=project_name,
        depth=depth,
        notes=notes,
        scoped_webs=scoped_webs,
        rendered_note_keys=rendered_note_keys,
        note_inline_context=note_inline_context,
    )
    return tuple(sections), extra_notes


def _resolve_strand_links(
    universe: tuple[MemoryStrand, ...],
    *,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
) -> tuple[ResolvedStrandLink, ...]:
    """Resolve authored links in every strand in a web's read universe."""
    edges: list[ResolvedStrandLink] = []
    for strand in universe:
        if strand.link_reference == "none":
            continue
        for link in scan_memory_links(strand.body):
            target = resolve_memory_link_target(
                link.target, notes=notes, scoped_webs=scoped_webs, source_strand=strand
            )
            if target is None:
                continue
            inline = depth != 0 and (link.inline or strand.link_rendering == "inline")
            if inline and always_reference_target(target):
                inline = False
            edges.append(ResolvedStrandLink(strand, link, inline, target))
    return tuple(edges)


def _apply_cross_web_root(
    sections: list[MemoryWebReadSection],
    by_slug: dict[str, ScopedMemoryWeb],
    source_strand: MemoryStrand,
    target: MemoryStrandLinkTarget,
    link: MemoryLink,
) -> None:
    """Add a cross-web inline target as a related root, if not already rendered."""
    _add_related_root(
        sections,
        by_slug,
        target,
        referrer=(source_strand.keyword, link.raw, "link"),
    )


def apply_note_strand_roots(
    sections: tuple[MemoryWebReadSection, ...],
    roots: list[PendingNoteStrandRoot],
    *,
    scoped_webs: tuple[ScopedMemoryWeb, ...],
) -> tuple[MemoryWebReadSection, ...]:
    """Add related roots from flat-note inline strand links."""
    if not roots:
        return sections
    by_slug = {scoped.slug: scoped for scoped in scoped_webs}
    merged = list(sections)
    for root in roots:
        _add_related_root(
            merged,
            by_slug,
            root.target,
            referrer=(root.source_note.relative_path, root.link.raw, "link"),
        )
    return tuple(merged)


def _add_related_root(
    sections: list[MemoryWebReadSection],
    by_slug: dict[str, ScopedMemoryWeb],
    target: MemoryStrandLinkTarget,
    *,
    referrer: tuple[str, str, GlossarySpanKind],
) -> None:
    """Append a target as a non-expanding related node in its web section."""
    node = MemoryWebReadNode(
        target.strand, target.scope, "related", _EXTRA_ROOT_DEPTH, referrer, ()
    )
    for index, section in enumerate(sections):
        if section.web.slug != target.web.slug:
            continue
        if any(
            existing.strand.slug == target.strand.slug for existing in section.nodes
        ):
            return
        sections[index] = replace(section, nodes=section.nodes + (node,))
        return
    scoped = by_slug.get(target.web.slug)
    if scoped is not None:
        sections.append(
            MemoryWebReadSection(
                web=replace(scoped.web, strands=scoped.strands),
                nodes=(node,),
                depth_limit=None,
                truncated=False,
            )
        )


def _resolve_cross_note_roots(
    pending: list[MemoryNoteLinkTarget],
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    depth: int | None,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    rendered_note_keys: frozenset[str],
    note_inline_context: NoteInlineContext,
) -> tuple[ResolvedMemoryNote, ...]:
    """Resolve web-to-note inline targets as separately rendered related notes."""
    extra_notes: list[ResolvedMemoryNote] = []
    seen_note_paths = set(rendered_note_keys)
    for target in pending:
        target_keys = note_target_keys(target)
        if target_keys & seen_note_paths:
            continue
        note = resolve_extra_note(
            target,
            project_root=project_root,
            home_root=home_root,
            project_name=project_name,
            notes=notes,
            scoped_webs=scoped_webs,
            depth=depth,
            seen_note_paths=frozenset(seen_note_paths | set(target_keys)),
            note_inline_context=note_inline_context,
        )
        if note is None:
            continue
        note = replace(note, render_origin="related")
        note_keys = note_tree_keys(note)
        if note_keys & seen_note_paths:
            continue
        seen_note_paths.update(note_keys)
        extra_notes.append(note)
    return tuple(extra_notes)


def _closure_node(
    node: GlossaryClosureNode,
    strand_by_index: dict[int, MemoryStrand],
    origins: dict[str, WebStrandOrigin],
    *,
    links: tuple[MemoryWebReadLink, ...] = (),
) -> MemoryWebReadNode:
    """Convert a core closure node into its selector-rendering representation."""
    strand = strand_by_index[node.entry.index]
    return MemoryWebReadNode(
        strand=strand,
        scope=origins[strand.slug].scope,
        origin=node.origin,
        depth=node.depth,
        referrer=None
        if node.referrer is None
        else (node.referrer.term, node.referrer.matched_text, node.referrer.kind),
        also_referenced_by=node.also_referenced_by,
        links=links,
    )
