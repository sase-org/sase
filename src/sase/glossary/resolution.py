"""Term-reference lookup and recursive glossary reference-closure resolution."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Literal

from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    GlossaryEntry,
    GlossarySpan,
    scan_glossary_spans,
)

_SEPARATOR_RE = re.compile(r"[-_\s]+")
_MAX_LOOKUP_CANDIDATES = 5


class GlossaryLookupError(ValueError):
    """Raised when a glossary reference cannot be resolved uniquely."""

    def __init__(
        self,
        reference: str,
        candidates: tuple[str, ...] = (),
    ) -> None:
        self.reference = reference
        self.candidates = candidates
        if candidates:
            hint = ", ".join(candidates)
            message = f"unknown glossary term: {reference} (did you mean: {hint})"
        else:
            message = f"unknown glossary term: {reference}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GlossaryReferrer:
    """The term and matched phrase that pulled a related node into a closure."""

    term: str
    matched_text: str


@dataclass(frozen=True, slots=True)
class GlossaryClosureNode:
    """One discovered glossary entry in a resolved closure."""

    entry: GlossaryEntry
    depth: int
    origin: Literal["requested", "related"]
    referrer: GlossaryReferrer | None
    also_referenced_by: tuple[str, ...]
    spans: tuple[GlossarySpan, ...]


@dataclass(frozen=True, slots=True)
class GlossaryClosure:
    """Deterministic BFS closure over glossary definition references."""

    nodes: tuple[GlossaryClosureNode, ...]
    roots: tuple[GlossaryEntry, ...]
    depth_limit: int | None
    truncated: bool


@dataclass
class _NodeBuilder:
    entry: GlossaryEntry
    depth: int
    origin: Literal["requested", "related"]
    referrer: GlossaryReferrer | None
    also_referenced_by: list[str] = field(default_factory=list)
    spans: tuple[GlossarySpan, ...] = ()

    def freeze(self) -> GlossaryClosureNode:
        return GlossaryClosureNode(
            entry=self.entry,
            depth=self.depth,
            origin=self.origin,
            referrer=self.referrer,
            also_referenced_by=tuple(self.also_referenced_by),
            spans=self.spans,
        )


class _LookupIndex:
    """Catalog-order indexes for exact, prefix, and substring term lookup."""

    def __init__(self, catalog: GlossaryCatalog) -> None:
        self.entries = catalog.entries
        self.by_index = {entry.index: entry for entry in catalog.entries}
        self._by_term: dict[str, GlossaryEntry] = {}
        self._by_alias: dict[str, GlossaryEntry] = {}
        self._keys_by_index: dict[int, tuple[str, ...]] = {}
        for entry in catalog.entries:
            keys = _entry_lookup_keys(entry)
            self._keys_by_index[entry.index] = keys
            term_key = normalize_glossary_reference(entry.normalized_term)
            display_key = normalize_glossary_reference(entry.term)
            if term_key:
                self._by_term.setdefault(term_key, entry)
            if display_key:
                self._by_term.setdefault(display_key, entry)
            for alias in entry.effective_aliases:
                alias_key = normalize_glossary_reference(alias)
                if alias_key:
                    self._by_alias.setdefault(alias_key, entry)

    def lookup(self, reference: str) -> GlossaryEntry:
        needle = normalize_glossary_reference(reference)
        if not needle:
            raise GlossaryLookupError(reference)

        exact_term = self._by_term.get(needle)
        if exact_term is not None:
            return exact_term

        exact_alias = self._by_alias.get(needle)
        if exact_alias is not None:
            return exact_alias

        prefix_match = self._unique_prefix_match(needle)
        if prefix_match is not None:
            return prefix_match

        raise GlossaryLookupError(reference, self._substring_candidates(needle))

    def _unique_prefix_match(self, needle: str) -> GlossaryEntry | None:
        matches: list[GlossaryEntry] = []
        for entry in self.entries:
            if any(key.startswith(needle) for key in self._keys_by_index[entry.index]):
                matches.append(entry)
        if len(matches) == 1:
            return matches[0]
        return None

    def _substring_candidates(self, needle: str) -> tuple[str, ...]:
        found: list[str] = []
        for entry in self.entries:
            if any(needle in key for key in self._keys_by_index[entry.index]):
                found.append(entry.term)
                if len(found) == _MAX_LOOKUP_CANDIDATES:
                    break
        return tuple(found)


def normalize_glossary_reference(value: str) -> str:
    """Casefold *value* and collapse runs of ``-``, ``_``, and whitespace to one space."""
    return _SEPARATOR_RE.sub(" ", value.casefold()).strip()


def resolve_glossary_closure(
    catalog: GlossaryCatalog,
    compiled: CompiledGlossaryCatalog | None,
    roots: Sequence[str | GlossaryEntry],
    depth: int | None = None,
    *,
    precomputed_spans: Mapping[int, Sequence[GlossarySpan]] | None = None,
) -> GlossaryClosure:
    """Resolve *roots* and walk definition references in deterministic BFS order.

    ``depth=None`` walks the full reachable closure. ``depth=0`` yields only the
    requested roots. When a finite limit cuts off an unseen reference, the
    result is marked ``truncated``.
    """
    if depth is not None and depth < 0:
        raise ValueError("glossary closure depth must be >= 0")

    index = _LookupIndex(catalog)
    resolved_roots = _resolve_roots(index, roots)
    if not resolved_roots:
        return GlossaryClosure(
            nodes=(),
            roots=(),
            depth_limit=depth,
            truncated=False,
        )

    builders: list[_NodeBuilder] = []
    builders_by_index: dict[int, _NodeBuilder] = {}
    queue: deque[_NodeBuilder] = deque()
    for entry in resolved_roots:
        if entry.index in builders_by_index:
            continue
        builder = _NodeBuilder(
            entry=entry,
            depth=0,
            origin="requested",
            referrer=None,
        )
        builders.append(builder)
        builders_by_index[entry.index] = builder
        queue.append(builder)

    truncated = False
    while queue:
        current = queue.popleft()
        current.spans = _spans_for(
            current.entry,
            compiled,
            precomputed_spans,
        )
        at_limit = depth is not None and current.depth >= depth
        for span in current.spans:
            target = index.by_index.get(span.entry_index)
            if target is None or target.index == current.entry.index:
                continue
            existing = builders_by_index.get(target.index)
            if existing is not None:
                _record_additional_referrer(existing, current.entry.term)
                continue
            if at_limit:
                truncated = True
                continue
            related = _NodeBuilder(
                entry=target,
                depth=current.depth + 1,
                origin="related",
                referrer=GlossaryReferrer(
                    term=current.entry.term,
                    matched_text=span.matched_text,
                ),
            )
            builders.append(related)
            builders_by_index[target.index] = related
            queue.append(related)

    return GlossaryClosure(
        nodes=tuple(builder.freeze() for builder in builders),
        roots=resolved_roots,
        depth_limit=depth,
        truncated=truncated,
    )


def _resolve_roots(
    index: _LookupIndex,
    roots: Sequence[str | GlossaryEntry],
) -> tuple[GlossaryEntry, ...]:
    resolved: list[GlossaryEntry] = []
    seen: set[int] = set()
    for root in roots:
        entry = root if isinstance(root, GlossaryEntry) else index.lookup(root)
        if entry.index in seen:
            continue
        seen.add(entry.index)
        resolved.append(entry)
    return tuple(resolved)


def _spans_for(
    entry: GlossaryEntry,
    compiled: CompiledGlossaryCatalog | None,
    precomputed_spans: Mapping[int, Sequence[GlossarySpan]] | None,
) -> tuple[GlossarySpan, ...]:
    if precomputed_spans is not None and entry.index in precomputed_spans:
        spans: Iterable[GlossarySpan] = precomputed_spans[entry.index]
    elif compiled is None:
        spans = ()
    else:
        spans = scan_glossary_spans(compiled, entry.definition.strip())
    return tuple(sorted(spans, key=lambda span: (span.byte_start, span.byte_end)))


def _record_additional_referrer(node: _NodeBuilder, referrer_term: str) -> None:
    if node.referrer is not None and node.referrer.term == referrer_term:
        return
    if referrer_term == node.entry.term:
        return
    if referrer_term in node.also_referenced_by:
        return
    node.also_referenced_by.append(referrer_term)


def _entry_lookup_keys(entry: GlossaryEntry) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in (entry.normalized_term, entry.term, *entry.effective_aliases):
        key = normalize_glossary_reference(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return tuple(keys)


__all__ = [
    "GlossaryClosure",
    "GlossaryClosureNode",
    "GlossaryLookupError",
    "GlossaryReferrer",
    "normalize_glossary_reference",
    "resolve_glossary_closure",
]
