"""Bridge from memory-web strands to the glossary phrase-closure engine.

A web's ``closure:`` frontmatter selects how far ``sase memory read`` walks
from requested strands: ``mentions`` reuses the same Rust phrase matcher the
glossary uses today, ``none`` (the default for every web except the
glossary) never expands past the requested strands. Reusing
:func:`~sase.glossary.resolution.resolve_glossary_closure` here is what lets
a future glossary migration read identically through
``sase memory read glossary:<term>``.
"""

from __future__ import annotations

from sase.core.glossary_facade import (
    GlossaryEntry,
    GlossaryInputEntry,
    build_glossary_catalog,
    compile_glossary_catalog,
)
from sase.glossary.resolution import GlossaryClosure, resolve_glossary_closure

from .models import MemoryStrand, MemoryWeb


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
    entries = [
        GlossaryInputEntry(
            term=strand.keyword,
            definition=strand.body,
            aliases=strand.aliases,
            source={"slug": strand.slug, "path": str(strand.path)},
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

    root_entries = [entry_by_slug[strand.slug] for strand in roots]
    closure = resolve_glossary_closure(catalog, compiled, root_entries, depth=depth)
    return closure, strand_by_index


__all__ = ["resolve_strand_closure"]
