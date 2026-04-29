"""Wire records for the sase query language.

Companion to :mod:`sase.core.wire`. Defines the **stable** boundary between
Python and a future Rust implementation of the query tokenizer/parser/evaluator
(Phase 2 of `research/202604/rust_backend_migration.md`).

The wire records intentionally do not subclass or share code with the Python
AST dataclasses in :mod:`sase.ace.query.types` — Python may keep evolving the
AST for ergonomics while this shape changes only with a schema bump.

JSON shape conventions:

- All keys are lowercase ``snake_case``.
- Tagged unions use a string ``kind`` field.
- ``None`` is preserved (becomes JSON ``null``).
- Lists are preserved (never replaced with ``None`` for empty branches).
- Positions are 0-based byte offsets into the original query string, matching
  the positions Python's tokenizer/parser emit in error messages.

Regex semantics inventory
-------------------------

The query language is **not** regex. String matching is plain substring
search (case-insensitive by default, case-sensitive with the ``c"..."``
prefix). The two ``re`` patterns in
:mod:`sase.ace.query.evaluator` (``_WORKSPACE_SUFFIX_RE`` and
``_LEGACY_READY_TO_MAIL_RE``) are internal status-string normalization
helpers and are never exposed to user input. Phase 2B/2C must reproduce
substring semantics — do not introduce a regex engine for user queries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

QUERY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class QueryTokenWire:
    """Wire form of a single :class:`sase.ace.query.tokenizer.Token`.

    Attributes:
        kind: Lowercase token type name, e.g. ``"string"``, ``"property"``,
            ``"and"``, ``"or"``, ``"not"``, ``"error_suffix"``,
            ``"not_error_suffix"``, ``"running_agent"``,
            ``"not_running_agent"``, ``"running_process"``,
            ``"not_running_process"``, ``"any_special"``, ``"lparen"``,
            ``"rparen"``, ``"eof"``.
        value: The token's textual value (string content for strings,
            property value for properties, the literal source for operators
            and shorthands).
        position: 0-based byte offset of the token within the original query.
        case_sensitive: For ``"string"`` tokens, whether the match is
            case-sensitive (``c"..."`` prefix). Defaults to ``False``.
        property_key: For ``"property"`` tokens, the property key
            (``"status"``, ``"project"``, ``"ancestor"``, ``"name"``,
            ``"sibling"``). ``None`` for all other token kinds.
    """

    kind: str
    value: str
    position: int
    case_sensitive: bool = False
    property_key: str | None = None


@dataclass(frozen=True)
class QueryExprWire:
    """JSON-safe tagged AST for one query expression node.

    A tagged union over five shapes, distinguished by ``kind``:

    - ``"string"``: a substring match. Uses ``value``, ``case_sensitive``,
      and the three ``is_*`` flags.
    - ``"property"``: a property filter. Uses ``property_key`` and ``value``.
    - ``"not"``: negation. Uses ``operands`` with exactly one element.
    - ``"and"`` / ``"or"``: n-ary conjunction/disjunction. Uses ``operands``
      with two or more elements.

    Fields not relevant for a given ``kind`` are left at their default
    (``""`` / ``False`` / ``None`` / ``[]``) so the dataclass shape stays
    rectangular for JSON consumers.

    Attributes:
        kind: One of ``"string"``, ``"property"``, ``"not"``, ``"and"``,
            ``"or"``.
        value: The string value for ``"string"`` and ``"property"`` nodes.
        case_sensitive: For ``"string"`` nodes, whether the match is
            case-sensitive.
        is_error_suffix: For ``"string"`` nodes, set when the node was
            produced by the ``!!!`` shorthand. Drives canonical-string
            output and evaluator special-casing.
        is_running_agent: For ``"string"`` nodes, set when produced by the
            ``@@@`` shorthand.
        is_running_process: For ``"string"`` nodes, set when produced by the
            ``$$$`` shorthand.
        property_key: For ``"property"`` nodes, the property key.
        operands: For ``"not"``, ``"and"``, ``"or"`` nodes, the child
            expressions.
    """

    kind: str
    value: str = ""
    case_sensitive: bool = False
    is_error_suffix: bool = False
    is_running_agent: bool = False
    is_running_process: bool = False
    property_key: str | None = None
    operands: tuple[QueryExprWire, ...] = ()


@dataclass(frozen=True)
class QueryProgramWire:
    """Serializable representation of a compiled query.

    Phase 2A keeps this plain-data so parity tests can compare programs
    produced by Python and Rust without going through an opaque handle.
    A future PyO3 binding may add an opaque ``handle`` field; until then
    the AST is the program.

    Attributes:
        schema_version: Bumped when the wire shape changes.
        source: The original query source string (kept for round-trip and
            error reporting).
        canonical: The canonical-form string from
            :func:`sase.ace.query.types.to_canonical_string`. Useful for
            equality checks across implementations that may differ in AST
            folding.
        ast: The root :class:`QueryExprWire`.
    """

    schema_version: int
    source: str
    canonical: str
    ast: QueryExprWire


# pyvision: tests/test_core_query_golden_errors.py
@dataclass(frozen=True)
class QueryErrorWire:
    """Structured error a Rust query implementation may emit.

    Attributes:
        kind: One of ``"tokenizer_error"`` or ``"parse_error"``.
        message: Human-readable message. Phase 2B/2C should match the
            Python message text closely enough that UI validation keeps
            working.
        position: 0-based byte offset within the source query, or ``-1``
            when the error has no specific position (e.g. empty query).
    """

    kind: str
    message: str
    position: int


# Token kind names exposed on the wire. Centralized so the converter and the
# Rust port use the exact same lowercase strings.
TOKEN_KIND_STRING = "string"
TOKEN_KIND_PROPERTY = "property"
TOKEN_KIND_AND = "and"
TOKEN_KIND_OR = "or"
TOKEN_KIND_NOT = "not"
TOKEN_KIND_ERROR_SUFFIX = "error_suffix"
TOKEN_KIND_NOT_ERROR_SUFFIX = "not_error_suffix"
TOKEN_KIND_RUNNING_AGENT = "running_agent"
TOKEN_KIND_NOT_RUNNING_AGENT = "not_running_agent"
TOKEN_KIND_RUNNING_PROCESS = "running_process"
TOKEN_KIND_NOT_RUNNING_PROCESS = "not_running_process"
TOKEN_KIND_ANY_SPECIAL = "any_special"
TOKEN_KIND_LPAREN = "lparen"
TOKEN_KIND_RPAREN = "rparen"
TOKEN_KIND_EOF = "eof"

EXPR_KIND_STRING = "string"
EXPR_KIND_PROPERTY = "property"
EXPR_KIND_NOT = "not"
EXPR_KIND_AND = "and"
EXPR_KIND_OR = "or"


# pyvision: tests/test_core_query_golden_wire.py
def query_wire_to_json_dict(record: Any) -> Any:
    """Project a query wire record (or list of them) to a JSON-safe shape.

    Mirrors :func:`sase.core.wire.to_json_dict` but is local to this module
    so query wire types stay independent of the parser wire module's
    schema bumps.
    """
    if isinstance(record, (list, tuple)):
        return [query_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: query_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


# Re-exports so callers can pick up the field default container without
# poking inside the dataclass.
__all__ = [
    "EXPR_KIND_AND",
    "EXPR_KIND_NOT",
    "EXPR_KIND_OR",
    "EXPR_KIND_PROPERTY",
    "EXPR_KIND_STRING",
    "QUERY_WIRE_SCHEMA_VERSION",
    "QueryErrorWire",
    "QueryExprWire",
    "QueryProgramWire",
    "QueryTokenWire",
    "TOKEN_KIND_AND",
    "TOKEN_KIND_ANY_SPECIAL",
    "TOKEN_KIND_EOF",
    "TOKEN_KIND_ERROR_SUFFIX",
    "TOKEN_KIND_LPAREN",
    "TOKEN_KIND_NOT",
    "TOKEN_KIND_NOT_ERROR_SUFFIX",
    "TOKEN_KIND_NOT_RUNNING_AGENT",
    "TOKEN_KIND_NOT_RUNNING_PROCESS",
    "TOKEN_KIND_OR",
    "TOKEN_KIND_PROPERTY",
    "TOKEN_KIND_RPAREN",
    "TOKEN_KIND_RUNNING_AGENT",
    "TOKEN_KIND_RUNNING_PROCESS",
    "TOKEN_KIND_STRING",
    "query_wire_to_json_dict",
]
