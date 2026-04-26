"""AST types for the agent query language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DurationOp = Literal["<", "<=", ">", ">=", "="]


@dataclass
class StringMatch:
    """A string match expression.

    Mirrors :class:`sase.ace.query.types.StringMatch` minus the ChangeSpec-only
    shorthand markers (``!!!``, ``@@@``, ``$$$``).
    """

    value: str
    case_sensitive: bool = False


@dataclass
class PropertyMatch:
    """A ``key:value`` filter for substring/enum/bool agent properties.

    The set of valid ``key`` values is closed and policed by the tokenizer;
    see :data:`sase.ace.agent_query.tokenizer.VALID_PROPERTY_KEYS`.
    """

    key: str
    value: str


@dataclass
class DurationCompare:
    """An ``age`` comparison such as ``age>2h`` or ``age<=15s``.

    Attributes:
        key: Always ``"age"`` in Phase 1; kept as a field so future duration
            keys (e.g. ``runtime``) slot in without an AST change.
        op: One of ``<``, ``<=``, ``>``, ``>=``, ``=``.
        seconds: The duration literal converted to whole seconds.
    """

    key: str
    op: DurationOp
    seconds: int


@dataclass
class NotExpr:
    """Negation expression."""

    operand: QueryExpr


@dataclass
class AndExpr:
    """AND expression (conjunction)."""

    operands: list[QueryExpr]


@dataclass
class OrExpr:
    """OR expression (disjunction)."""

    operands: list[QueryExpr]


QueryExpr = StringMatch | PropertyMatch | DurationCompare | NotExpr | AndExpr | OrExpr


def _escape_string_value(value: str) -> str:
    """Escape special characters in a string value for display."""
    result = value.replace("\\", "\\\\")
    result = result.replace('"', '\\"')
    result = result.replace("\n", "\\n")
    result = result.replace("\r", "\\r")
    result = result.replace("\t", "\\t")
    return result


def _format_duration(seconds: int) -> str:
    """Render a whole-second duration as the largest exact unit literal.

    The tokenizer only accepts whole-unit literals (``1h``, ``30m``); we round
    back into the same shape so canonicalization is a true round-trip.
    """
    for unit_seconds, suffix in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds % unit_seconds == 0:
            return f"{seconds // unit_seconds}{suffix}"
    return f"{seconds}s"


def to_canonical_string(expr: QueryExpr) -> str:
    """Convert a query expression to its canonical string representation.

    Examples:
        >>> to_canonical_string(StringMatch("foo"))
        '"foo"'
        >>> to_canonical_string(PropertyMatch("status", "failed"))
        'status:failed'
        >>> to_canonical_string(DurationCompare("age", ">", 7200))
        'age>2h'
    """
    if isinstance(expr, StringMatch):
        escaped = _escape_string_value(expr.value)
        if expr.case_sensitive:
            return f'c"{escaped}"'
        return f'"{escaped}"'

    if isinstance(expr, PropertyMatch):
        return f"{expr.key}:{expr.value}"

    if isinstance(expr, DurationCompare):
        return f"{expr.key}{expr.op}{_format_duration(expr.seconds)}"

    if isinstance(expr, NotExpr):
        inner = to_canonical_string(expr.operand)
        if isinstance(expr.operand, (AndExpr, OrExpr)):
            return f"NOT ({inner})"
        return f"NOT {inner}"

    if isinstance(expr, AndExpr):
        parts = []
        for op in expr.operands:
            inner = to_canonical_string(op)
            if isinstance(op, OrExpr):
                inner = f"({inner})"
            parts.append(inner)
        return " AND ".join(parts)

    if isinstance(expr, OrExpr):
        parts = []
        for op in expr.operands:
            inner = to_canonical_string(op)
            if isinstance(op, AndExpr):
                inner = f"({inner})"
            parts.append(inner)
        return " OR ".join(parts)

    raise TypeError(f"Unknown expression type: {type(expr)}")  # pragma: no cover
