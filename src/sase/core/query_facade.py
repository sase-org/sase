"""sase.core facade for query parse/build/evaluate entry points.

Wraps :mod:`sase.ace.query`. The only dispatched seam in this module is
:func:`parse_query`, which routes to a Rust binding when the optional
``sase_core_rs`` extension exposes ``parse_query``.

Per-row callers (:func:`evaluate_query`, :func:`evaluate_query_with_context`),
:func:`build_query_context`, and the batch :func:`evaluate_query_many` are
intentionally Python-owned host logic and call their ``*_python``
implementations directly. They are not "fallbacks" — see the Phase 8A
handoff operation disposition and Phase 8B's evaluate_query_many deferral
(``plans/202604/rust_backend_phase8_phase8b_handoff.md``): the routed Rust
path stayed 6-9x slower than the optimised Python batch path because PyO3
must rebuild ``ChangeSpecWire`` from a fresh dict on every call.
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
from sase.core.backend import dispatch, load_rust_extension
from sase.core.query_wire_conversion import (
    query_expr_from_wire,
    query_expr_wire_from_dict,
)


def _rust_parse_query_impl(query: str) -> QueryExpr:
    """Adapter from ``sase_core_rs.parse_query`` to the Python AST.

    The PyO3 binding returns a dict in the rectangular Python wire shape;
    this rebuilds a :class:`QueryExprWire` and projects it to the existing
    :class:`QueryExpr` dataclass tree so callers see the same return type
    regardless of backend.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    record: dict[str, Any] = rust_module.parse_query(query)  # type: ignore[attr-defined]
    return query_expr_from_wire(query_expr_wire_from_dict(record))


def parse_query(query: str) -> QueryExpr:
    """Parse a query string into a :class:`QueryExpr` via the active backend."""
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_parse_query_impl
        if rust_module is not None and hasattr(rust_module, "parse_query")
        else None
    )
    return dispatch(
        operation="parse_query",
        python_impl=parse_query_python,
        rust_impl=rust_impl,
        args=(query,),
    )


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
