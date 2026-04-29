"""sase.core facade for query parse/build/evaluate entry points.

Wraps :mod:`sase.ace.query` behind :func:`sase.core.backend.dispatch` so the
parse, build-context, and evaluate operations can each be replaced
independently by a Rust implementation. The Python implementations are kept
under ``*_python`` aliases (imported below) so tests that need to bypass
dispatch can call them directly without re-implementing the seam.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.context import (
    QueryEvaluationContext,
    build_query_context_python,
    evaluate_query_python,
    evaluate_query_with_context_python,
)
from sase.ace.query.parser import parse_query_python
from sase.ace.query.types import QueryExpr
from sase.core.backend import dispatch


def parse_query(query: str) -> QueryExpr:
    """Parse a query string into a :class:`QueryExpr` via the active backend."""
    return dispatch(
        operation="parse_query",
        python_impl=parse_query_python,
        args=(query,),
    )


def build_query_context(changespecs: list[ChangeSpec]) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` via the active backend."""
    return dispatch(
        operation="build_query_context",
        python_impl=build_query_context_python,
        args=(changespecs,),
    )


def evaluate_query(
    query: QueryExpr,
    changespec: ChangeSpec,
    all_changespecs: list[ChangeSpec] | None = None,
) -> bool:
    """Evaluate ``query`` against ``changespec`` via the active backend."""
    return dispatch(
        operation="evaluate_query",
        python_impl=evaluate_query_python,
        args=(query, changespec, all_changespecs),
    )


def evaluate_query_with_context(
    query: QueryExpr,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` using a shared context via the active backend."""
    return dispatch(
        operation="evaluate_query_with_context",
        python_impl=evaluate_query_with_context_python,
        args=(query, changespec, ctx),
    )
