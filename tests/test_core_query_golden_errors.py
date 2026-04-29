"""User-visible parser/tokenizer error messages for malformed input.

The shape mirrors :class:`QueryErrorWire` (kind/message/position) so a
Rust port can reuse the same fixtures via JSON.
"""

from __future__ import annotations

import pytest
from inline_snapshot import snapshot

from sase.ace.query.parser import QueryParseError, parse_query_python
from sase.core.query_wire import QueryErrorWire

from tests._query_golden_corpus import MALFORMED_QUERIES


def test_malformed_query_messages_snapshot() -> None:
    """Pin user-visible parser/tokenizer errors for malformed input."""
    errors: dict[str, dict[str, object]] = {}
    for q in MALFORMED_QUERIES:
        with pytest.raises(QueryParseError) as exc:
            parse_query_python(q)
        wire_error = QueryErrorWire(
            kind="parse_error",
            message=str(exc.value),
            position=exc.value.position,
        )
        errors[q] = {
            "position": wire_error.position,
            "message": wire_error.message,
        }
    assert errors == snapshot(
        {
            "": {"position": 0, "message": "Empty query (at position 0)"},
            '"unterminated': {
                "position": 0,
                "message": "Unterminated string at position 0 (at position 0)",
            },
            '"\\x"': {
                "position": 1,
                "message": "Invalid escape sequence: \\x at position 1 (at position 1)",
            },
            "AND": {
                "position": 0,
                "message": "Expected string or '(', got AND (at position 0)",
            },
            "(": {
                "position": 1,
                "message": "Expected string or '(', got EOF (at position 1)",
            },
            ")": {
                "position": 0,
                "message": "Expected string or '(', got ) (at position 0)",
            },
            "alpha AND": {
                "position": 9,
                "message": "Expected string or '(', got EOF (at position 9)",
            },
            "%q": {
                "position": 0,
                "message": "Invalid status shorthand (use %d, %m, %r, %s, %w, or %y) at position 0 (at position 0)",
            },
            "+": {
                "position": 0,
                "message": "Expected project name after '+' at position 0 (at position 0)",
            },
            "+1abc": {
                "position": 0,
                "message": "Expected project name after '+' at position 0 (at position 0)",
            },
            "unknown:value": {
                "position": 0,
                "message": "Unknown property key: unknown (valid keys: status, project, ancestor, name, sibling) at position 0 (at position 0)",
            },
            "@bad": {
                "position": 0,
                "message": "Unexpected character: @ at position 0 (at position 0)",
            },
            "$bad": {
                "position": 0,
                "message": "Unexpected character: $ at position 0 (at position 0)",
            },
            "*bad": {
                "position": 0,
                "message": "Unexpected character: * at position 0 (at position 0)",
            },
        }
    )
