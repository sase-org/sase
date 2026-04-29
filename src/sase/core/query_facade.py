"""sase.core facade for query parse/build/evaluate entry points.

Phase 0A: thin wrappers around :mod:`sase.ace.query`. Phase 0B routes the
public functions through these dispatched entry points.
"""

from __future__ import annotations

from sase.ace.changespec.models import ChangeSpec
from sase.ace.query.evaluator import (
    QueryEvaluationContext,
    build_query_context as _python_build_query_context,
    evaluate_query as _python_evaluate_query,
    evaluate_query_with_context as _python_evaluate_query_with_context,
)
from sase.ace.query.parser import parse_query as _python_parse_query
from sase.ace.query.types import QueryExpr
from sase.core.backend import dispatch


def parse_query(query: str) -> QueryExpr:
    """Parse a query string into a :class:`QueryExpr` via the active backend."""
    return dispatch(
        operation="parse_query",
        python_impl=_python_parse_query,
        args=(query,),
    )


def build_query_context(changespecs: list[ChangeSpec]) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext` via the active backend."""
    return dispatch(
        operation="build_query_context",
        python_impl=_python_build_query_context,
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
        python_impl=_python_evaluate_query,
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
        python_impl=_python_evaluate_query_with_context,
        args=(query, changespec, ctx),
    )
