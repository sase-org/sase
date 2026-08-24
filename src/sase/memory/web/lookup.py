"""Lookup helpers for memory-web strands."""

from __future__ import annotations

from collections import defaultdict

from sase.core.glossary_facade import (
    GlossaryCatalog,
    GlossaryInputEntry,
    build_glossary_catalog,
)
from sase.glossary.resolution import normalize_glossary_reference

from .models import MemoryStrand, MemoryWeb


class MemoryWebLookupError(ValueError):
    """Raised when a strand selector is unknown or ambiguous."""


def normalize_memory_web_reference(value: str) -> str:
    """Normalize a strand selector the same way glossary references do."""

    return normalize_glossary_reference(value)


def strand_glossary_catalog(strands: tuple[MemoryStrand, ...]) -> GlossaryCatalog:
    """Return the Rust-derived glossary catalog for *strands*, in order."""

    entries = [
        GlossaryInputEntry(
            term=strand.keyword,
            definition=strand.body,
            aliases=strand.aliases,
        )
        for strand in strands
    ]
    return build_glossary_catalog(entries)


def _effective_aliases(strands: tuple[MemoryStrand, ...]) -> dict[str, tuple[str, ...]]:
    catalog = strand_glossary_catalog(strands)
    return {
        strand.slug: catalog_entry.effective_aliases
        for strand, catalog_entry in zip(strands, catalog.entries, strict=True)
    }


def resolve_memory_strand(web: MemoryWeb, reference: str) -> MemoryStrand:
    """Resolve *reference* by slug, keyword, alias, then unique normalized prefix."""

    for strand in web.strands:
        if reference == strand.slug:
            return strand

    needle = normalize_memory_web_reference(reference)
    if not needle:
        raise MemoryWebLookupError(f"unknown memory strand: {reference}")

    by_keyword = {
        normalize_memory_web_reference(strand.keyword): strand for strand in web.strands
    }
    exact_keyword = by_keyword.get(needle)
    if exact_keyword is not None:
        return exact_keyword

    effective_aliases = _effective_aliases(web.strands)
    by_alias: dict[str, MemoryStrand] = {}
    for strand in web.strands:
        for alias in effective_aliases.get(strand.slug, strand.aliases):
            key = normalize_memory_web_reference(alias)
            if key:
                by_alias.setdefault(key, strand)
    exact_alias = by_alias.get(needle)
    if exact_alias is not None:
        return exact_alias

    keys_by_slug: dict[str, set[str]] = defaultdict(set)
    for strand in web.strands:
        for value in (strand.slug, strand.keyword, *effective_aliases[strand.slug]):
            key = normalize_memory_web_reference(value)
            if key:
                keys_by_slug[strand.slug].add(key)

    matches = [
        strand
        for strand in web.strands
        if any(key.startswith(needle) for key in keys_by_slug[strand.slug])
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(strand.keyword for strand in matches[:5])
        raise MemoryWebLookupError(
            f"ambiguous memory strand {reference!r} in {web.slug}: {choices}"
        )
    raise MemoryWebLookupError(f"unknown memory strand {web.slug}:{reference}")


__all__ = [
    "MemoryWebLookupError",
    "normalize_memory_web_reference",
    "resolve_memory_strand",
    "strand_glossary_catalog",
]
