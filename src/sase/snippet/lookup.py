"""Exact, alias, and unique-prefix lookup over a snippet catalog."""

from __future__ import annotations

from dataclasses import dataclass

from sase.snippet.models import SnippetCatalog, SnippetEntry

_MAX_CANDIDATES = 5


@dataclass(frozen=True, slots=True)
class _LookupFailure:
    reference: str
    candidates: tuple[str, ...]


class SnippetLookupError(ValueError):
    """Raised when a trigger cannot be resolved uniquely."""

    def __init__(
        self,
        reference: str,
        candidates: tuple[str, ...] = (),
    ) -> None:
        self.reference = reference
        self.candidates = candidates
        if candidates:
            hint = ", ".join(candidates)
            message = f"unknown snippet trigger: {reference} (did you mean: {hint})"
        else:
            message = f"unknown snippet trigger: {reference}"
        super().__init__(message)
        self.failures = (_LookupFailure(reference=reference, candidates=candidates),)


def lookup_snippet(catalog: SnippetCatalog, reference: str) -> SnippetEntry:
    """Resolve *reference* to one explicit catalog entry.

    Exact explicit triggers win, then generated aliases, then a unique prefix
    across both. Ambiguous prefixes raise :class:`SnippetLookupError`.
    """
    needle = reference.strip()
    if not needle:
        raise SnippetLookupError(reference)

    by_trigger = {entry.trigger: entry for entry in catalog.entries}
    if needle in by_trigger:
        return by_trigger[needle]

    source = catalog.alias_provenance.get(needle)
    if source is not None and source in by_trigger:
        return by_trigger[source]

    keys = (*by_trigger, *catalog.alias_provenance)
    prefix_hits = [key for key in keys if key.startswith(needle)]
    unique_sources: list[str] = []
    seen: set[str] = set()
    for key in prefix_hits:
        resolved = catalog.alias_provenance.get(key, key)
        if resolved in seen or resolved not in by_trigger:
            continue
        seen.add(resolved)
        unique_sources.append(resolved)
    if len(unique_sources) == 1:
        return by_trigger[unique_sources[0]]

    candidates = tuple(
        unique_sources[:_MAX_CANDIDATES] or _substring_candidates(catalog, needle)
    )
    raise SnippetLookupError(reference, candidates)


def _substring_candidates(catalog: SnippetCatalog, needle: str) -> tuple[str, ...]:
    lowered = needle.casefold()
    hits = [
        entry.trigger
        for entry in catalog.entries
        if lowered in entry.trigger.casefold()
    ]
    return tuple(hits[:_MAX_CANDIDATES])


__all__ = ["SnippetLookupError", "lookup_snippet"]
