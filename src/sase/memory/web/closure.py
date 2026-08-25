"""Bridge from memory-web strands to the glossary phrase-closure engine.

A web's ``closure:`` frontmatter selects how far ``sase memory read`` walks
from requested strands: ``mentions`` reuses the same Rust phrase matcher the
glossary uses today, ``none`` (the default for every web except the
glossary) never expands past the requested strands. Reusing
:func:`~sase.memory.web.resolution.resolve_glossary_closure` here keeps
``sase memory read glossary:<term>`` aligned with prompt highlighting.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    GlossaryEntry,
    GlossaryInputEntry,
    build_glossary_catalog,
    compile_glossary_catalog,
)
from sase.memory.web.relations import glossary_reverse_references
from sase.memory.web.resolution import GlossaryClosure, resolve_glossary_closure

from .models import MemoryStrand, MemoryWeb


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


def build_strand_mention_catalog(
    web: MemoryWeb, universe: tuple[MemoryStrand, ...]
) -> StrandMentionCatalog:
    """Compile *universe* into a glossary catalog for closure/relation lookups.

    ``universe`` is every strand the closure may expand into (the scope-merged
    strand set). The reverse-mention index is only built when *web* declares
    ``closure: mentions``, matching the phrase matcher itself.
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
    compiled = compile_glossary_catalog(entries) if web.closure == "mentions" else None

    strand_by_index: dict[int, MemoryStrand] = {}
    entry_by_slug: dict[str, GlossaryEntry] = {}
    for strand, entry in zip(universe, catalog.entries, strict=True):
        strand_by_index[entry.index] = strand
        entry_by_slug[strand.slug] = entry

    reverse = (
        glossary_reverse_references(catalog, compiled) if compiled is not None else {}
    )
    return StrandMentionCatalog(
        catalog=catalog,
        compiled=compiled,
        reverse=reverse,
        strand_by_index=strand_by_index,
        entry_by_slug=entry_by_slug,
    )


def resolve_strand_closure(
    web: MemoryWeb,
    universe: tuple[MemoryStrand, ...],
    roots: tuple[MemoryStrand, ...],
    *,
    depth: int | None,
) -> tuple[GlossaryClosure, dict[int, MemoryStrand]]:
    """Resolve *roots* against every strand in *universe* for one web.

    ``universe`` is every strand the closure may expand into (the scope-merged
    strand set); ``roots`` are the strands directly requested by the caller.
    Returns the closure plus a map from catalog entry index back to the
    :class:`MemoryStrand` it was built from, since :class:`GlossaryEntry`
    carries no slug or path.
    """
    mention_catalog = build_strand_mention_catalog(web, universe)
    root_entries = [mention_catalog.entry_by_slug[strand.slug] for strand in roots]
    closure = resolve_glossary_closure(
        mention_catalog.catalog, mention_catalog.compiled, root_entries, depth=depth
    )
    return closure, dict(mention_catalog.strand_by_index)


def strand_mention_relations(
    mention_catalog: StrandMentionCatalog, strand: MemoryStrand
) -> tuple[tuple[MemoryStrand, ...], tuple[MemoryStrand, ...]]:
    """Return ordered ``(outbound, inbound)`` mention-related strands for *strand*.

    Outbound is *strand*'s own depth-1 closure (the terms its body mentions);
    inbound is every strand whose body mentions *strand*, from the cached
    reverse index. Both are empty when *strand* is not in this catalog, e.g. a
    stale selection from a since-edited web.
    """
    own_entry = mention_catalog.entry_by_slug.get(strand.slug)
    if own_entry is None:
        return (), ()
    closure = resolve_glossary_closure(
        mention_catalog.catalog, mention_catalog.compiled, (own_entry,), depth=1
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
    "StrandMentionCatalog",
    "build_strand_mention_catalog",
    "resolve_strand_closure",
    "strand_mention_relations",
]
