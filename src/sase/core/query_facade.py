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

from typing import Any

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.context import (
    QueryEvaluationContext,
    build_query_context_python,
    evaluate_query_python,
    evaluate_query_with_context_python,
)
from sase.ace.query.types import QueryExpr
from sase.core.query_wire_conversion import (
    query_expr_from_wire,
    query_expr_wire_from_dict,
)
from sase.core.rust import require_rust_binding


def parse_query(query: str) -> QueryExpr:
    """Parse a query string into a :class:`QueryExpr` via ``sase_core_rs``."""
    rust_parse_query = require_rust_binding("parse_query")
    record: dict[str, Any] = rust_parse_query(query)
    return query_expr_from_wire(query_expr_wire_from_dict(record))


def build_query_context(changespecs: list[ChangeSpec]) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` (Python-owned host logic)."""
    return build_query_context_python(changespecs)


def evaluate_query(
    query: QueryExpr,
    changespec: ChangeSpec,
    all_changespecs: list[ChangeSpec] | None = None,
) -> bool:
    """Evaluate ``query`` against ``changespec`` (Python-owned host logic)."""
    return evaluate_query_python(query, changespec, all_changespecs)


def evaluate_query_with_context(
    query: QueryExpr,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` using a shared context (Python-owned host logic)."""
    return evaluate_query_with_context_python(query, changespec, ctx)


def evaluate_query_many(
    query: str,
    changespecs: list[ChangeSpec],
) -> list[bool]:
    """Evaluate ``query`` against every ChangeSpec in one batch call.

    Compatibility API for callers that do not own a reusable corpus. Hot paths
    should call :func:`sase.core.query_corpus_facade.compile_query_corpus` once
    per stable ``list[ChangeSpec]`` identity and then use
    :func:`sase.core.query_corpus_facade.evaluate_query_many_with_corpus`.
    """
    from sase.core.query_corpus_facade import (
        compile_query_corpus,
        evaluate_query_many_with_corpus,
    )

    corpus = compile_query_corpus(changespecs)
    return evaluate_query_many_with_corpus(query, corpus)
