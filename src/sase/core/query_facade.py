"""sase.core facade for query parse/build/evaluate entry points.

Wraps :mod:`sase.ace.query`. The only Rust-bound seam in this module is
:func:`parse_query`, which Phase 8D rewired to call ``sase_core_rs``
directly through :func:`sase.core.rust.require_rust_binding`. The
returned dict is rehydrated into the existing :class:`QueryExpr`
dataclass tree via :func:`query_expr_wire_from_dict` /
:func:`query_expr_from_wire`. The Python parser is no longer reachable
through this facade after Phase 8D; tests that need the Python AST
builder import :func:`sase.ace.query.parser.parse_query_python`
directly.

Per-row callers (:func:`evaluate_query`, :func:`evaluate_query_with_context`),
:func:`build_query_context`, and the batch :func:`evaluate_query_many`
are intentionally Python-owned host logic and call their ``*_python``
implementations directly. They are not "fallbacks" — see the Phase 8A
handoff operation disposition and Phase 8B's evaluate_query_many
deferral (``plans/202604/rust_backend_phase8_phase8b_handoff.md``):
the routed Rust path stayed 6-9x slower than the optimised Python batch
path because PyO3 must rebuild ``ChangeSpecWire`` from a fresh dict on
every call.
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
    """Parse a query string into a :class:`QueryExpr` via ``sase_core_rs``.

    Calls the Rust ``parse_query`` binding directly and rehydrates the
    returned dict into the existing :class:`QueryExpr` dataclass tree via
    :func:`query_expr_wire_from_dict` / :func:`query_expr_from_wire`. The
    Python parser is no longer reachable through this facade after
    Phase 8D; tests that need the Python AST builder import
    :func:`sase.ace.query.parser.parse_query_python` directly.
    """
    rust_parse_query = require_rust_binding("parse_query")
    record: dict[str, Any] = rust_parse_query(query)
    return query_expr_from_wire(query_expr_wire_from_dict(record))


def build_query_context(changespecs: list[ChangeSpec]) -> QueryEvaluationContext:
    """Build a :class:`QueryEvaluationContext`.

    Intentionally Python-owned host logic — see Phase 8A handoff
    operation disposition.
    """
    return build_query_context_python(changespecs)


def evaluate_query(
    query: QueryExpr,
    changespec: ChangeSpec,
    all_changespecs: list[ChangeSpec] | None = None,
) -> bool:
    """Evaluate ``query`` against ``changespec``.

    Intentionally Python-owned host logic — see Phase 8A handoff
    operation disposition.
    """
    return evaluate_query_python(query, changespec, all_changespecs)


def evaluate_query_with_context(
    query: QueryExpr,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    """Evaluate ``query`` using a shared context.

    Intentionally Python-owned host logic — see Phase 8A handoff
    operation disposition.
    """
    return evaluate_query_with_context_python(query, changespec, ctx)


def _evaluate_query_many_python(
    query: str,
    changespecs: list[ChangeSpec],
) -> list[bool]:
    """Python implementation of :func:`evaluate_query_many`.

    Parses the query once and evaluates against every ChangeSpec using a
    shared :class:`QueryEvaluationContext` so name/status/searchable maps
    are computed only once per list. This is the authoritative implementation
    for :func:`evaluate_query_many` after Phase 8B's deferral decision.
    """
    expr = parse_query_python(query)
    ctx = build_query_context_python(changespecs)
    return [evaluate_query_with_context_python(expr, cs, ctx) for cs in changespecs]


def evaluate_query_many(
    query: str,
    changespecs: list[ChangeSpec],
) -> list[bool]:
    """Evaluate ``query`` against every ChangeSpec in one batch call.

    The hot-path filter API for TUI/CLI lists. Phase 8B reclassified this
    surface as deferred/unported (the routed Rust path was 6-9x slower than
    the optimised Python batch path); Phase 8C drops the dispatcher seam
    entirely and routes directly through the Python batch implementation.
    See ``plans/202604/rust_backend_phase8_phase8b_handoff.md``.
    """
    return _evaluate_query_many_python(query, changespecs)
