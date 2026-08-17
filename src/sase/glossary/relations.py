"""Inbound glossary relation index built from definition spans."""

from __future__ import annotations

from collections.abc import Mapping

from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    scan_glossary_spans,
)


def glossary_reverse_references(
    catalog: GlossaryCatalog, compiled: CompiledGlossaryCatalog
) -> Mapping[int, tuple[str, ...]]:
    """Map each entry index to the terms whose definitions reference it.

    Self-references are dropped. When one definition mentions another term
    more than once, that referrer is recorded a single time, in catalog order.
    """
    inbound: dict[int, list[str]] = {entry.index: [] for entry in catalog.entries}
    known = {entry.index for entry in catalog.entries}
    for entry in catalog.entries:
        seen: set[int] = set()
        for span in scan_glossary_spans(compiled, entry.definition.strip()):
            target = span.entry_index
            if target not in known or target == entry.index or target in seen:
                continue
            seen.add(target)
            inbound[target].append(entry.term)
    return {index: tuple(terms) for index, terms in inbound.items()}


__all__ = ["glossary_reverse_references"]
