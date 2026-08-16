"""Rust-routed corpus facade for profile-driven Artifacts pane queries.

Wraps the generic ``compile_corpus_with_profile`` / ``compile_query_with_profile``
/ ``evaluate_many`` / ``parse_query_with_profile`` Rust bindings with
immutable row/index/result records so flat Artifacts panes route production
filtering through Rust handles. Row coercion is shared with the Python reference
evaluator via
:func:`sase.ace.query.profile_evaluator.coerce_artifact_query_row`, so the
two evaluators always agree on what one row means; the reference evaluator in
:mod:`sase.ace.query.profile_evaluator` stays parity-test-only, not a
production fallback for *matching*.

One asymmetry is load-bearing: relative date literals (``since:2d``,
``until:today``) can only be resolved against "now" in the configured
timezone, which is host (Python) config the profile itself never carries.
Rust's parser/canonicalizer treat a ``date``-kind value as opaque text, so
:func:`evaluate_artifact_query_many` always canonicalizes through
:func:`sase.ace.query.profile_reference.canonical_query_for_profile` (which
resolves relative dates to epoch seconds) before handing the *already*
literal canonical text to Rust for the actual batch match. This module's own
:func:`parse_artifact_query` wrapper stays available for parser parity testing.

Callers build one :class:`ArtifactQueryIndex` per pane snapshot off the
Textual event loop, then evaluate many queries against it as the user types.
:class:`ArtifactQueryCacheKey` gives every filter session the same exact
cache key shape -- ``(pane_id, generation, profile_digest, canonical_query)``
-- so a stale worker result or a changed dialect can never be mistaken for a
cache hit.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from sase.ace.query.profile_evaluator import (
    ArtifactQueryRow,
    ArtifactQueryRowInput,
    coerce_artifact_query_row,
)
from sase.ace.query.profile_reference import canonical_query_for_profile
from sase.ace.query.types import QueryExpr
from sase.ace.query_profile import CompiledQueryProfile
from sase.core.query_wire_conversion import (
    query_expr_from_wire,
    query_expr_wire_from_dict,
)
from sase.core.rust import require_rust_binding


class ArtifactQueryCacheKey(NamedTuple):
    """Exact cache key for one pane's compiled query-evaluation result."""

    pane_id: str
    generation: int
    profile_digest: str
    canonical_query: str


@dataclass(frozen=True, slots=True)
class ArtifactQueryIndex:
    """An immutable, off-thread-built Rust corpus for one pane snapshot."""

    pane_id: str
    generation: int
    profile: CompiledQueryProfile
    row_ids: tuple[str, ...]
    facets: Mapping[str, tuple[str, ...]]
    rust_handle: Any

    def __len__(self) -> int:
        return len(self.row_ids)

    def cache_key(self, canonical_query: str) -> ArtifactQueryCacheKey:
        return ArtifactQueryCacheKey(
            pane_id=self.pane_id,
            generation=self.generation,
            profile_digest=self.profile.digest,
            canonical_query=canonical_query,
        )

    def validate(self) -> None:
        """Raise if the wrapper no longer matches the owned Rust corpus."""
        actual_length = _rust_corpus_length(self.rust_handle)
        if actual_length != len(self.row_ids):
            raise ValueError(
                f"stale query index for pane {self.pane_id!r}: expected "
                f"{len(self.row_ids)} rows but Rust handle contains "
                f"{actual_length}; rebuild the index for the current snapshot"
            )


@dataclass(frozen=True, slots=True)
class ArtifactQueryResult:
    """One evaluated query's matched row ids, keyed for caller-side caching."""

    cache_key: ArtifactQueryCacheKey
    matched_row_ids: tuple[str, ...]


def compile_artifact_query_index(
    *,
    pane_id: str,
    generation: int,
    profile: CompiledQueryProfile,
    entries: Iterable[ArtifactQueryRowInput],
) -> ArtifactQueryIndex:
    """Build a Rust corpus and observed facets for *entries*.

    Intended to run on a worker thread alongside the owning snapshot build,
    never on the Textual event loop: row coercion and Rust corpus indexing
    are both real work proportional to entry count.
    """

    rows = tuple(coerce_artifact_query_row(profile, entry) for entry in entries)
    compile_corpus = require_rust_binding("compile_corpus_with_profile")
    wire_rows = [_row_wire(row) for row in rows]
    rust_handle = compile_corpus(profile.to_wire(), wire_rows)
    return ArtifactQueryIndex(
        pane_id=pane_id,
        generation=generation,
        profile=profile,
        row_ids=tuple(row.stable_id for row in rows),
        facets=_observed_facets(profile, rows),
        rust_handle=rust_handle,
    )


def evaluate_artifact_query_many(
    query: str,
    index: ArtifactQueryIndex,
    *,
    canonical_query: str | None = None,
) -> ArtifactQueryResult:
    """Evaluate *query* against a previously compiled :class:`ArtifactQueryIndex`.

    *query* is always canonicalized through the date-aware Python reference
    parser before Rust ever sees it, so a relative date literal resolves
    against "now" once here rather than being matched as opaque text. Pass
    an already-computed *canonical_query* (from
    :func:`sase.ace.query.profile_reference.canonical_query_for_profile`)
    when the caller has one, to avoid re-resolving it.
    """

    index.validate()
    resolved_canonical = (
        canonical_query
        if canonical_query is not None
        else canonical_query_for_profile(query, index.profile)
    )
    compile_query = require_rust_binding("compile_query_with_profile")
    evaluate_many = require_rust_binding("evaluate_many")
    program = compile_query(resolved_canonical, index.profile.to_wire())
    matches = evaluate_many(program, index.rust_handle)
    matched = tuple(
        row_id
        for row_id, is_match in zip(index.row_ids, matches, strict=True)
        if is_match
    )
    return ArtifactQueryResult(
        cache_key=index.cache_key(resolved_canonical),
        matched_row_ids=matched,
    )


def parse_artifact_query(query: str, profile: CompiledQueryProfile) -> QueryExpr:
    """Parse *query* under *profile* through the Rust parser."""

    rust_parse = require_rust_binding("parse_query_with_profile")
    record: dict[str, Any] = rust_parse(query, profile.to_wire())
    return query_expr_from_wire(query_expr_wire_from_dict(record))


def _row_wire(row: ArtifactQueryRow) -> dict[str, Any]:
    return {
        "fields": {key: list(values) for key, values in row.fields.items()},
        "searchable_text": row.searchable_text,
        "predicates": {
            "error_suffix": "error_suffix" in row.predicates,
            "running_agent": "running_agent" in row.predicates,
            "running_process": "running_process" in row.predicates,
        },
    }


def _observed_facets(
    profile: CompiledQueryProfile,
    rows: Sequence[ArtifactQueryRow],
) -> Mapping[str, tuple[str, ...]]:
    """Distinct observed values per filterable field, for FilterBar completion."""

    filterable_keys = tuple(item.key for item in profile.fields if item.filterable)
    observed: dict[str, set[str]] = {key: set() for key in filterable_keys}
    for row in rows:
        for key in filterable_keys:
            for value in row.fields.get(key, ()):
                observed[key].add(str(value))
    return {key: tuple(sorted(values)) for key, values in observed.items() if values}


def _rust_corpus_length(rust_handle: Any) -> int:
    try:
        return len(rust_handle)
    except TypeError as exc:
        raise TypeError(
            "Rust query corpus handle does not expose __len__; reinstall with "
            "`just install` (or `just rust-install`) before using the "
            "profile-driven query corpus facade."
        ) from exc


__all__ = [
    "ArtifactQueryCacheKey",
    "ArtifactQueryIndex",
    "ArtifactQueryResult",
    "compile_artifact_query_index",
    "evaluate_artifact_query_many",
    "parse_artifact_query",
]
