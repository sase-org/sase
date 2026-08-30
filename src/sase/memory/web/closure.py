"""Bridge from memory-web strands to the glossary phrase-closure engine.

A web's effective ``link_reference`` selects how far ``sase memory read``
walks from requested strands: ``implicit`` compiles the same Rust phrase
matcher the glossary uses today, ``explicit`` only follows authored
``[[...]]``/``![[...]]`` links, ``none`` never expands past the requested
strands. Reusing :func:`~sase.memory.web.resolution.resolve_glossary_closure`
here keeps ``sase memory read glossary:<term>`` aligned with prompt
highlighting.

Authored links are folded into the same closure walk as synthetic
:class:`~sase.core.glossary_facade.GlossarySpan` entries: a caller resolves
each strand's ``[[target]]``/``![[target]]`` links against the full memory
universe (see :mod:`sase.memory.link_resolve`) and passes the ones that
target a strand in *this* web's own universe as :class:`StrandLinkSpan`
values. Cross-web and flat-note targets can't become a span in this web's
catalog (there is no entry for them), so the caller handles those directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    GlossaryEntry,
    GlossaryInputEntry,
    GlossarySpan,
    build_glossary_catalog,
    compile_glossary_catalog,
    scan_glossary_spans,
)
from sase.memory.links import scan_memory_links
from sase.memory.web.relations import glossary_reverse_references
from sase.memory.web.resolution import GlossaryClosure, resolve_glossary_closure

from .lookup import MemoryWebLookupError, resolve_memory_strand
from .models import MemoryStrand, MemoryWeb


@dataclass(frozen=True, slots=True)
class StrandLinkSpan:
    """One authored inline link, pre-resolved to a same-web target strand."""

    source_slug: str
    target_slug: str
    raw: str
    span: tuple[int, int]


@dataclass(frozen=True, slots=True)
class StrandMentionCatalog:
    """One web's strands compiled into a glossary catalog, with a reverse index.

    Building and compiling the catalog is the expensive step (it compiles a
    phrase matcher), so callers on a selection-change path must cache one of
    these per web load rather than rebuilding it per keystroke.
    """

    catalog: GlossaryCatalog
    compiled: CompiledGlossaryCatalog | None
    reverse: Mapping[int, tuple[str, ...]]
    strand_by_index: Mapping[int, MemoryStrand]
    entry_by_slug: Mapping[str, GlossaryEntry]
    spans_by_index: Mapping[int, tuple[GlossarySpan, ...]]


def build_strand_mention_catalog(
    web: MemoryWeb,
    universe: tuple[MemoryStrand, ...],
    *,
    link_spans: tuple[StrandLinkSpan, ...] = (),
) -> StrandMentionCatalog:
    """Compile *universe* into a glossary catalog for closure/relation lookups.

    ``universe`` is every strand the closure may expand into (the scope-merged
    strand set). The phrase matcher is only compiled when *web* declares
    ``link_reference: implicit`` (or the legacy ``closure: mentions`` alias).
    *link_spans* are same-web authored inline links, already resolved by the
    caller; they become synthetic spans merged with any phrase-mention spans,
    per source strand, honoring each strand's own effective
    ``link_reference`` (``none`` suppresses both kinds for that strand).
    """
    entries = [
        GlossaryInputEntry(
            term=strand.keyword,
            definition=strand.body,
            aliases=strand.aliases,
            source={"slug": strand.slug, "source_path": str(strand.path)},
        )
        for strand in universe
    ]
    catalog = build_glossary_catalog(entries)
    needs_matcher = web.link_reference == "implicit"
    compiled = compile_glossary_catalog(entries) if needs_matcher else None

    strand_by_index: dict[int, MemoryStrand] = {}
    entry_by_slug: dict[str, GlossaryEntry] = {}
    for strand, entry in zip(universe, catalog.entries, strict=True):
        strand_by_index[entry.index] = strand
        entry_by_slug[strand.slug] = entry

    link_spans_by_source: dict[int, list[GlossarySpan]] = {}
    for edge in link_spans:
        source_entry = entry_by_slug.get(edge.source_slug)
        target_entry = entry_by_slug.get(edge.target_slug)
        if source_entry is None or target_entry is None:
            continue
        link_spans_by_source.setdefault(source_entry.index, []).append(
            GlossarySpan(
                term=target_entry.term,
                entry_index=target_entry.index,
                alias_index=-1,
                alias="",
                matched_text=edge.raw,
                byte_start=edge.span[0],
                byte_end=edge.span[1],
                range={},
                segments=(),
                kind="link",
            )
        )

    spans_by_index: dict[int, tuple[GlossarySpan, ...]] = {}
    if compiled is not None or link_spans_by_source:
        for strand, entry in zip(universe, catalog.entries, strict=True):
            link_only = tuple(link_spans_by_source.get(entry.index, ()))
            mention_spans: tuple[GlossarySpan, ...] = ()
            if compiled is not None and strand.link_reference == "implicit":
                mention_spans = scan_glossary_spans(compiled, entry.definition.strip())
            spans_by_index[entry.index] = tuple(
                sorted(
                    (*mention_spans, *link_only),
                    key=lambda span: (span.byte_start, span.byte_end),
                )
            )

    reverse = (
        glossary_reverse_references(catalog, spans_by_index) if spans_by_index else {}
    )
    return StrandMentionCatalog(
        catalog=catalog,
        compiled=compiled,
        reverse=reverse,
        strand_by_index=strand_by_index,
        entry_by_slug=entry_by_slug,
        spans_by_index=spans_by_index,
    )


def _local_strand_target(web: MemoryWeb, reference: str) -> str | None:
    """Resolve *reference* to a strand slug within *web*, or ``None``.

    Handles the bare keyword/slug/alias form and the ``web:keyword`` /
    ``web/slug`` forms when the web part names *web* itself. Cross-web and
    flat-note targets return ``None`` -- this lookup only sees one web.
    """
    candidate = reference.strip()
    for separator in (":", "/"):
        if separator in candidate:
            web_part, _, rest = candidate.partition(separator)
            if web_part.strip() != web.slug:
                return None
            candidate = rest.strip()
            break
    if candidate.endswith(".md"):
        candidate = candidate[: -len(".md")]
    if not candidate:
        return None
    try:
        return resolve_memory_strand(web, candidate).slug
    except MemoryWebLookupError:
        return None


def strand_link_spans(
    web: MemoryWeb, universe: tuple[MemoryStrand, ...]
) -> tuple[StrandLinkSpan, ...]:
    """Return same-web authored link edges within *universe*.

    Resolves each authored ``[[target]]``/``![[target]]`` link purely against
    *universe* itself (bare keyword/slug/alias, or ``web:keyword``/``web/slug``
    naming this same web); it can't see cross-web or flat-note targets. For
    the full memory universe (the cross-unit expansion
    ``sase.memory.selector`` performs for ``sase memory read``), the caller
    resolves links itself and passes the same-web subset in as *link_spans*
    instead of calling this.
    """
    merged = replace(web, strands=universe)
    spans: list[StrandLinkSpan] = []
    for strand in universe:
        if strand.link_reference == "none":
            continue
        for link in scan_memory_links(strand.body):
            target_slug = _local_strand_target(merged, link.target)
            if target_slug is None or target_slug == strand.slug:
                continue
            spans.append(
                StrandLinkSpan(
                    source_slug=strand.slug,
                    target_slug=target_slug,
                    raw=link.raw,
                    span=link.span,
                )
            )
    return tuple(spans)


def resolve_strand_closure(
    web: MemoryWeb,
    universe: tuple[MemoryStrand, ...],
    roots: tuple[MemoryStrand, ...],
    *,
    depth: int | None,
    link_spans: tuple[StrandLinkSpan, ...] = (),
) -> tuple[GlossaryClosure, dict[int, MemoryStrand]]:
    """Resolve *roots* against every strand in *universe* for one web.

    ``universe`` is every strand the closure may expand into (the scope-merged
    strand set); ``roots`` are the strands directly requested by the caller.
    Returns the closure plus a map from catalog entry index back to the
    :class:`MemoryStrand` it was built from, since :class:`GlossaryEntry`
    carries no slug or path.
    """
    mention_catalog = build_strand_mention_catalog(web, universe, link_spans=link_spans)
    root_entries = [mention_catalog.entry_by_slug[strand.slug] for strand in roots]
    closure = resolve_glossary_closure(
        mention_catalog.catalog,
        mention_catalog.compiled,
        root_entries,
        depth=depth,
        precomputed_spans=mention_catalog.spans_by_index or None,
    )
    return closure, dict(mention_catalog.strand_by_index)


def strand_mention_relations(
    mention_catalog: StrandMentionCatalog, strand: MemoryStrand
) -> tuple[tuple[MemoryStrand, ...], tuple[MemoryStrand, ...]]:
    """Return ordered ``(outbound, inbound)`` link/mention-related strands for *strand*.

    Outbound is *strand*'s own depth-1 closure (the terms its body mentions or
    links); inbound is every strand whose body references *strand*, from the
    cached reverse index. Both are empty when *strand* is not in this catalog,
    e.g. a stale selection from a since-edited web.
    """
    own_entry = mention_catalog.entry_by_slug.get(strand.slug)
    if own_entry is None:
        return (), ()
    closure = resolve_glossary_closure(
        mention_catalog.catalog,
        mention_catalog.compiled,
        (own_entry,),
        depth=1,
        precomputed_spans=mention_catalog.spans_by_index or None,
    )
    outbound = tuple(
        mention_catalog.strand_by_index[node.entry.index]
        for node in closure.nodes
        if node.origin == "related"
    )
    inbound_terms = mention_catalog.reverse.get(own_entry.index, ())
    by_keyword = {s.keyword: s for s in mention_catalog.strand_by_index.values()}
    inbound = tuple(by_keyword[term] for term in inbound_terms if term in by_keyword)
    return outbound, inbound


__all__ = [
    "StrandLinkSpan",
    "StrandMentionCatalog",
    "build_strand_mention_catalog",
    "resolve_strand_closure",
    "strand_link_spans",
    "strand_mention_relations",
]
