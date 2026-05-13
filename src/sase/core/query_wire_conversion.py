"""Convert query language tokens / AST nodes to and from wire records.

These helpers are the only place :mod:`sase.ace.query` Python types touch the
wire shape defined in :mod:`sase.core.query_wire`. Phase 2A uses them to pin
parity tests; Phase 2D uses :func:`query_expr_wire_from_dict` to consume the
dict shape returned by the Rust ``sase_core_rs`` PyO3 binding.
"""

from __future__ import annotations

from typing import Any

from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.core.query_wire import (
    EXPR_KIND_AND,
    EXPR_KIND_NOT,
    EXPR_KIND_OR,
    EXPR_KIND_PROPERTY,
    EXPR_KIND_STRING,
    QueryExprWire,
)


def _query_expr_to_wire(expr: QueryExpr) -> QueryExprWire:
    """Project a :class:`QueryExpr` AST to its tagged wire shape.

    Lists of operands become tuples so the wire record stays hashable and
    immutable.
    """
    if isinstance(expr, StringMatch):
        return QueryExprWire(
            kind=EXPR_KIND_STRING,
            value=expr.value,
            case_sensitive=expr.case_sensitive,
            is_error_suffix=expr.is_error_suffix,
            is_running_agent=expr.is_running_agent,
            is_running_process=expr.is_running_process,
        )
    if isinstance(expr, PropertyMatch):
        return QueryExprWire(
            kind=EXPR_KIND_PROPERTY,
            value=expr.value,
            property_key=expr.key,
        )
    if isinstance(expr, NotExpr):
        return QueryExprWire(
            kind=EXPR_KIND_NOT,
            operands=(_query_expr_to_wire(expr.operand),),
        )
    if isinstance(expr, AndExpr):
        return QueryExprWire(
            kind=EXPR_KIND_AND,
            operands=tuple(_query_expr_to_wire(op) for op in expr.operands),
        )
    if isinstance(expr, OrExpr):
        return QueryExprWire(
            kind=EXPR_KIND_OR,
            operands=tuple(_query_expr_to_wire(op) for op in expr.operands),
        )
    raise TypeError(f"Unknown query expression type: {type(expr)!r}")


def query_expr_from_wire(wire: QueryExprWire) -> QueryExpr:
    """Inverse of :func:`_query_expr_to_wire`.

    Raises ``ValueError`` if ``wire.kind`` is unknown or the operand count
    is wrong for the kind.
    """
    if wire.kind == EXPR_KIND_STRING:
        return StringMatch(
            value=wire.value,
            case_sensitive=wire.case_sensitive,
            is_error_suffix=wire.is_error_suffix,
            is_running_agent=wire.is_running_agent,
            is_running_process=wire.is_running_process,
        )
    if wire.kind == EXPR_KIND_PROPERTY:
        if wire.property_key is None:
            raise ValueError("property wire node missing property_key")
        return PropertyMatch(key=wire.property_key, value=wire.value)
    if wire.kind == EXPR_KIND_NOT:
        if len(wire.operands) != 1:
            raise ValueError(
                f"not wire node must have exactly one operand, got {len(wire.operands)}"
            )
        return NotExpr(operand=query_expr_from_wire(wire.operands[0]))
    if wire.kind == EXPR_KIND_AND:
        if len(wire.operands) < 2:
            raise ValueError(
                f"and wire node must have >= 2 operands, got {len(wire.operands)}"
            )
        return AndExpr(operands=[query_expr_from_wire(op) for op in wire.operands])
    if wire.kind == EXPR_KIND_OR:
        if len(wire.operands) < 2:
            raise ValueError(
                f"or wire node must have >= 2 operands, got {len(wire.operands)}"
            )
        return OrExpr(operands=[query_expr_from_wire(op) for op in wire.operands])
    raise ValueError(f"Unknown query expression kind: {wire.kind!r}")


def query_expr_wire_from_dict(record: dict[str, Any]) -> QueryExprWire:
    """Rebuild a :class:`QueryExprWire` from the Rust PyO3 dict shape.

    The Rust ``sase_core_rs.parse_query`` binding returns dicts in the
    rectangular shape Python expects (``kind`` plus all of ``value``,
    ``case_sensitive``, the three ``is_*`` flags, ``property_key``, and
    ``operands``). This helper wraps that into the typed
    :class:`QueryExprWire` so downstream code can use
    :func:`query_expr_from_wire` unchanged.
    """
    operands = tuple(
        query_expr_wire_from_dict(op) for op in record.get("operands") or ()
    )
    return QueryExprWire(
        kind=record["kind"],
        value=record.get("value", ""),
        case_sensitive=bool(record.get("case_sensitive", False)),
        is_error_suffix=bool(record.get("is_error_suffix", False)),
        is_running_agent=bool(record.get("is_running_agent", False)),
        is_running_process=bool(record.get("is_running_process", False)),
        property_key=record.get("property_key"),
        operands=operands,
    )
