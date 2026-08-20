"""sase.core facade for query parse/build/evaluate entry points.

:func:`parse_query` calls ``sase_core_rs.parse_query`` directly through
:func:`sase.core.rust.require_rust_binding` and rehydrates the returned
dict into the existing :class:`QueryExpr` dataclass tree. Tests that need
the Python AST builder import the private reference parser directly.

Per-row callers (:func:`evaluate_query`, :func:`evaluate_query_with_context`)
and :func:`build_query_context` remain Python-owned host logic. The batch
:func:`evaluate_query_many` compatibility entry point routes through the
persistent Rust query corpus path by compiling a temporary corpus for callers
that have not yet adopted an explicit cached corpus.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.ace.patch.models import Patch
from sase.ace.query.context import (
    QueryEvaluationContext,
    build_query_context_python,
    evaluate_query_python,
    evaluate_query_with_context_python,
)
from sase.ace.query.profile_reference import (
    ArtifactQueryRowInput,
    evaluate_query_many_for_profile,
)
from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.ace.query.parser import QueryParseError
from sase.ace.query.types import QueryExpr, StringMatch
from sase.ace.query_profile import CompiledQueryProfile
from sase.core.query_wire_conversion import (
    query_expr_from_wire,
    query_expr_wire_from_dict,
)
from sase.core.rust import require_rust_binding


def parse_query(query: str) -> QueryExpr:
    """Parse a query string into a :class:`QueryExpr` via ``sase_core_rs``."""
    try:
        remainder, _cap = extract_limit(query)
    except LimitTokenError as exc:
        raise QueryParseError(exc.message, exc.start) from exc
    if not remainder.strip():
        return StringMatch("")
    rust_parse_query = require_rust_binding("parse_query")
    record: dict[str, Any] = rust_parse_query(remainder)
    return query_expr_from_wire(query_expr_wire_from_dict(record))


def build_query_context(patches: list[Patch]) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` (Python-owned host logic)."""
    return build_query_context_python(patches)


def evaluate_query(
    query: QueryExpr,
    patch: Patch,
    all_patches: list[Patch] | None = None,
) -> bool:
    """Evaluate ``query`` against ``patch`` (Python-owned host logic)."""
    return evaluate_query_python(query, patch, all_patches)


def evaluate_query_with_context(
    query: QueryExpr,
    patch: Patch,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` using a shared context (Python-owned host logic)."""
    return evaluate_query_with_context_python(query, patch, ctx)


def evaluate_query_many(
    query: str,
    patches: list[Patch],
) -> list[bool]:
    """Evaluate ``query`` against every Patch in one batch call.

    Compatibility API for callers that do not own a reusable corpus. Hot paths
    should call :func:`sase.core.query_corpus_facade.compile_query_corpus` once
    per stable ``list[Patch]`` identity and then use
    :func:`sase.core.query_corpus_facade.evaluate_query_many_with_corpus`.
    """
    from sase.core.query_corpus_facade import (
        QueryCorpus,
        compile_query_corpus,
        evaluate_query_many_with_corpus,
    )

    corpus: QueryCorpus = compile_query_corpus(patches)
    return evaluate_query_many_with_corpus(query, corpus)


def evaluate_artifact_query_many(
    query: str,
    entries: Iterable[ArtifactQueryRowInput],
    profile: CompiledQueryProfile,
) -> list[bool]:
    """Evaluate a profile-driven Artifacts query against every entry."""

    return evaluate_query_many_for_profile(query, entries, profile)
