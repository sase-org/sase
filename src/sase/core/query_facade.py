"""sase.core facade for query parse/build/evaluate entry points.

:func:`parse_query` calls ``sase_core_rs.parse_query`` directly through
:func:`sase.core.rust.require_rust_binding` and rehydrates the returned
dict into the existing :class:`QueryExpr` dataclass tree. Tests that need
the Python AST builder import :func:`sase.ace.query.parser.parse_query_python`
directly.

Per-row callers (:func:`evaluate_query`, :func:`evaluate_query_with_context`),
:func:`build_query_context`, and the batch :func:`evaluate_query_many` are
Python-owned host logic. ``evaluate_query_many`` is the deferred entry: a
prototype Rust path was 6-9x slower than the optimised Python batch path
because PyO3 had to rebuild ``ChangeSpecWire`` from a fresh dict on every
call, so the public surface keeps the Python implementation until either
the wire conversion is amortised in Rust or the call pattern changes.
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
from sase.ace.query.parser import parse_query_python
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


def _evaluate_query_many_python(
    query: str,
    changespecs: list[ChangeSpec],
) -> list[bool]:
    """Parse ``query`` once and evaluate against every ChangeSpec.

    Builds a shared :class:`QueryEvaluationContext` so name/status/searchable
    maps are computed only once per list.
    """
    expr = parse_query_python(query)
    ctx = build_query_context_python(changespecs)
    return [evaluate_query_with_context_python(expr, cs, ctx) for cs in changespecs]


def evaluate_query_many(
    query: str,
    changespecs: list[ChangeSpec],
) -> list[bool]:
    """Evaluate ``query`` against every ChangeSpec in one batch call.

    Hot-path filter API for TUI/CLI lists. Routes directly through the
    Python batch implementation — see the module docstring for the deferral
    rationale.
    """
    return _evaluate_query_many_python(query, changespecs)
