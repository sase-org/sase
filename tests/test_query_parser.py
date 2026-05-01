"""Tests for the query language parser (AST building)."""

import pytest
from sase.ace.query import (
    AndExpr,
    OrExpr,
    QueryParseError,
    StringMatch,
    parse_query,
)
from sase.ace.query.parser import _parse_query_python
from sase.ace.query.types import ERROR_SUFFIX_QUERY


def test_parse_error_empty_query() -> None:
    """Test error on empty query.

    Calls ``_parse_query_python`` directly: Phase 8D rewired the public
    :func:`sase.ace.query.parse_query` to call the Rust binding, which
    raises a plain ``ValueError`` with a different message shape. The
    Python parser's :class:`QueryParseError` contract is what this
    suite pins.
    """
    with pytest.raises(QueryParseError) as exc_info:
        _parse_query_python("")
    assert "Empty query" in str(exc_info.value)


def test_parse_error_unmatched_paren() -> None:
    """Test error on unmatched parenthesis (Python parser-specific error)."""
    with pytest.raises(QueryParseError) as exc_info:
        _parse_query_python('("a"')
    assert "RPAREN" in str(exc_info.value)


def test_parse_error_missing_operand() -> None:
    """Test error on missing operand after AND (Python parser-specific error)."""
    with pytest.raises(QueryParseError) as exc_info:
        _parse_query_python('"a" AND')
    assert "Expected" in str(exc_info.value)


def test_parse_implicit_and_with_parens() -> None:
    """Test implicit AND with parentheses."""
    result = parse_query('"a" ("b" OR "c")')
    assert isinstance(result, AndExpr)
    assert len(result.operands) == 2
    assert isinstance(result.operands[0], StringMatch)
    assert isinstance(result.operands[1], OrExpr)


def test_parse_standalone_exclamation() -> None:
    """Test parsing standalone ! as error suffix search."""
    result = parse_query("!")
    assert isinstance(result, StringMatch)
    assert result.value == ERROR_SUFFIX_QUERY
    assert result.is_error_suffix is True


def test_parse_error_suffix_and_string() -> None:
    """Test parsing !!! AND "foo"."""
    result = parse_query('!!! AND "foo"')
    assert isinstance(result, AndExpr)
    assert len(result.operands) == 2
    assert isinstance(result.operands[0], StringMatch)
    assert result.operands[0].is_error_suffix is True
    assert isinstance(result.operands[1], StringMatch)
    assert result.operands[1].value == "foo"
