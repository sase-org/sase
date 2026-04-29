"""sase.core facade for query parse/build/evaluate entry points.

Wraps :mod:`sase.ace.query` behind :func:`sase.core.backend.dispatch` so the
parse, build-context, and evaluate operations can each be replaced
independently by a Rust implementation. The Python implementations are kept
under ``*_python`` aliases (imported below) so tests that need to bypass
dispatch can call them directly without re-implementing the seam.

Phase 2D registered a Rust implementation for :func:`parse_query` whenever
the optional ``sase_core_rs`` extension is importable. Per-row callers
(:func:`evaluate_query`, :func:`evaluate_query_with_context`) keep the Python
backend because the perf gain in Phase 2 lives in the batch path; routing
single rows through PyO3 would just pay FFI cost per spec.

Phase 8B reclassified :func:`evaluate_query_many` as deferred/unported
(see ``plans/202604/rust_backend_phase8_phase8b_handoff.md``). Even with the
wire-conversion cost amortized outside the timed window, the Rust path stays
6-9x slower than the optimised Python batch path because PyO3 must
deserialize every spec dict into ``ChangeSpecWire`` on each call. The facade
therefore routes through the Python batch implementation under all backends;
the corresponding Rust adapter has been removed and ``sase_core_rs`` no
longer participates in this surface until a future Rust port lands a
persistent corpus handle that beats the Python batch path.
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
    """Build a :class:`QueryEvaluationContext` via the active backend."""
    return dispatch(
        operation="build_query_context",
        python_impl=build_query_context_python,
        rust_unavailable="python",
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
        rust_unavailable="python",
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
        rust_unavailable="python",
        args=(query, changespec, ctx),
    )


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
    surface as deferred/unported: the dispatcher routes to the Python batch
    implementation regardless of ``SASE_CORE_BACKEND`` because the routed
    Rust path remains 6-9x slower than the optimised Python batch path
    (PyO3 must rebuild ``ChangeSpecWire`` from a fresh dict on every call).
    """
    return dispatch(
        operation="evaluate_query_many",
        python_impl=_evaluate_query_many_python,
        rust_unavailable="python",
        args=(query, changespecs),
    )
