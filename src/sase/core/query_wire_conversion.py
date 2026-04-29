"""Convert query language tokens / AST nodes to and from wire records.

These helpers are the only place :mod:`sase.ace.query` Python types touch the
wire shape defined in :mod:`sase.core.query_wire`. Phase 2A uses them to pin
parity tests; Phase 2D will use the inverse direction to consume the dict
shape returned by the Rust ``sase_core_rs`` PyO3 binding.
"""

from __future__ import annotations

from sase.ace.query.tokenizer import Token, TokenType
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
    to_canonical_string,
)
from sase.core.query_wire import (
    EXPR_KIND_AND,
    EXPR_KIND_NOT,
    EXPR_KIND_OR,
    EXPR_KIND_PROPERTY,
    EXPR_KIND_STRING,
    QUERY_WIRE_SCHEMA_VERSION,
    QueryExprWire,
    QueryProgramWire,
    QueryTokenWire,
    TOKEN_KIND_AND,
    TOKEN_KIND_ANY_SPECIAL,
    TOKEN_KIND_EOF,
    TOKEN_KIND_ERROR_SUFFIX,
    TOKEN_KIND_LPAREN,
    TOKEN_KIND_NOT,
    TOKEN_KIND_NOT_ERROR_SUFFIX,
    TOKEN_KIND_NOT_RUNNING_AGENT,
    TOKEN_KIND_NOT_RUNNING_PROCESS,
    TOKEN_KIND_OR,
    TOKEN_KIND_PROPERTY,
    TOKEN_KIND_RPAREN,
    TOKEN_KIND_RUNNING_AGENT,
    TOKEN_KIND_RUNNING_PROCESS,
    TOKEN_KIND_STRING,
)

_TOKEN_TYPE_TO_WIRE: dict[TokenType, str] = {
    TokenType.STRING: TOKEN_KIND_STRING,
    TokenType.PROPERTY: TOKEN_KIND_PROPERTY,
    TokenType.AND: TOKEN_KIND_AND,
    TokenType.OR: TOKEN_KIND_OR,
    TokenType.NOT: TOKEN_KIND_NOT,
    TokenType.ERROR_SUFFIX: TOKEN_KIND_ERROR_SUFFIX,
    TokenType.NOT_ERROR_SUFFIX: TOKEN_KIND_NOT_ERROR_SUFFIX,
    TokenType.RUNNING_AGENT: TOKEN_KIND_RUNNING_AGENT,
    TokenType.NOT_RUNNING_AGENT: TOKEN_KIND_NOT_RUNNING_AGENT,
    TokenType.RUNNING_PROCESS: TOKEN_KIND_RUNNING_PROCESS,
    TokenType.NOT_RUNNING_PROCESS: TOKEN_KIND_NOT_RUNNING_PROCESS,
    TokenType.ANY_SPECIAL: TOKEN_KIND_ANY_SPECIAL,
    TokenType.LPAREN: TOKEN_KIND_LPAREN,
    TokenType.RPAREN: TOKEN_KIND_RPAREN,
    TokenType.EOF: TOKEN_KIND_EOF,
}

_WIRE_TO_TOKEN_TYPE: dict[str, TokenType] = {
    v: k for k, v in _TOKEN_TYPE_TO_WIRE.items()
}


# pyvision: tests/test_core_query_golden.py
def token_to_wire(token: Token) -> QueryTokenWire:
    """Project a tokenizer :class:`Token` to its wire record."""
    return QueryTokenWire(
        kind=_TOKEN_TYPE_TO_WIRE[token.type],
        value=token.value,
        position=token.position,
        case_sensitive=token.case_sensitive,
        property_key=token.property_key,
    )


# pyvision: tests/test_core_query_golden.py
def token_from_wire(wire: QueryTokenWire) -> Token:
    """Inverse of :func:`token_to_wire`."""
    return Token(
        type=_WIRE_TO_TOKEN_TYPE[wire.kind],
        value=wire.value,
        case_sensitive=wire.case_sensitive,
        position=wire.position,
        property_key=wire.property_key,
    )


# pyvision: tests/test_core_query_golden.py
def query_expr_to_wire(expr: QueryExpr) -> QueryExprWire:
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
            operands=(query_expr_to_wire(expr.operand),),
        )
    if isinstance(expr, AndExpr):
        return QueryExprWire(
            kind=EXPR_KIND_AND,
            operands=tuple(query_expr_to_wire(op) for op in expr.operands),
        )
    if isinstance(expr, OrExpr):
        return QueryExprWire(
            kind=EXPR_KIND_OR,
            operands=tuple(query_expr_to_wire(op) for op in expr.operands),
        )
    raise TypeError(f"Unknown query expression type: {type(expr)!r}")


# pyvision: tests/test_core_query_golden.py
def query_expr_from_wire(wire: QueryExprWire) -> QueryExpr:
    """Inverse of :func:`query_expr_to_wire`.

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


# pyvision: tests/test_core_query_golden.py
def build_query_program_wire(source: str, expr: QueryExpr) -> QueryProgramWire:
    """Bundle a parsed expression into a :class:`QueryProgramWire`."""
    return QueryProgramWire(
        schema_version=QUERY_WIRE_SCHEMA_VERSION,
        source=source,
        canonical=to_canonical_string(expr),
        ast=query_expr_to_wire(expr),
    )
