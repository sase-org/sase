"""Evaluator for query expressions against ChangeSpecs.

The evaluator is split across sibling modules:

- :mod:`.searchable` — extracts searchable text from a ChangeSpec.
- :mod:`.matchers` — string and property matchers plus the recursive
  stateless :func:`~.matchers.evaluate`.
- :mod:`.introspection` — query AST introspection helpers
  (terminal/submitted/project filter detection).
- :mod:`.context` — :class:`QueryEvaluationContext` and the cached
  per-list-version evaluation path.

This module re-exports the public surface and defines the top-level
:func:`evaluate_query` entry point.
"""

from ..changespec import ChangeSpec
from .context import (
    QueryEvaluationContext,
    build_query_context,
    build_query_context_python,
    evaluate_query_python,
    evaluate_query_with_context,
    evaluate_query_with_context_python,
)
from .introspection import (
    get_sole_project_filter,
    query_explicitly_targets_submitted,
    query_explicitly_targets_terminal,
)
from .searchable import get_searchable_text
from .types import QueryExpr

__all__ = [
    "QueryEvaluationContext",
    "build_query_context",
    "build_query_context_python",
    "evaluate_query",
    "evaluate_query_python",
    "evaluate_query_with_context",
    "evaluate_query_with_context_python",
    "get_searchable_text",
    "get_sole_project_filter",
    "query_explicitly_targets_submitted",
    "query_explicitly_targets_terminal",
]


def evaluate_query(
    query: QueryExpr,
    changespec: ChangeSpec,
    all_changespecs: list[ChangeSpec] | None = None,
) -> bool:
    """Evaluate a query expression against a ChangeSpec.

    Public entry point — routes through :mod:`sase.core.query`. The default
    backend dispatches back to :func:`evaluate_query_python`.

    Examples:
        >>> from .parser import parse_query
        >>> query = parse_query('"feature"')
        >>> cs = ChangeSpec(name="my_feature", ...)
        >>> evaluate_query(query, cs)
        True
    """
    from sase.core.query_facade import evaluate_query as _facade

    return _facade(query, changespec, all_changespecs)
