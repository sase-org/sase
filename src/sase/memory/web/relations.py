"""Inbound glossary relation index built from definition spans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.core.glossary_facade import GlossaryCatalog, GlossarySpan


def glossary_reverse_references(
    catalog: GlossaryCatalog,
    spans_by_index: Mapping[int, Sequence[GlossarySpan]],
) -> Mapping[int, tuple[str, ...]]:
    """Map each entry index to the terms whose spans (mentions or links) reference it.

    *spans_by_index* is each entry's own precomputed outbound spans (mention
    spans, synthetic link spans, or both), keyed by entry index. Self-references
    are dropped. When one definition references another term more than once,
    that referrer is recorded a single time, in catalog order.
    """
    inbound: dict[int, list[str]] = {entry.index: [] for entry in catalog.entries}
    known = {entry.index for entry in catalog.entries}
    for entry in catalog.entries:
        seen: set[int] = set()
        for span in spans_by_index.get(entry.index, ()):
            target = span.entry_index
            if target not in known or target == entry.index or target in seen:
                continue
            seen.add(target)
            inbound[target].append(entry.term)
    return {index: tuple(terms) for index, terms in inbound.items()}


__all__ = ["glossary_reverse_references"]
