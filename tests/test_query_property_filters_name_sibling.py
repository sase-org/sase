"""Tests for name and sibling property filter functionality in the query language."""

from typing import Any

import pytest
from sase.ace.query import (
    evaluate_query,
    parse_query,
)
from sase.ace.query.tokenizer import TokenizerError, TokenType, tokenize

# --- Sibling Filter Tokenizer Tests ---


def test_tokenize_sibling_shorthand() -> None:
    """Test tokenizing ~name as sibling:name."""
    tokens = list(tokenize("~sibling_name"))
    assert len(tokens) == 2
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].value == "sibling_name"
    assert tokens[0].property_key == "sibling"


# --- Name Filter Tokenizer Tests ---


def test_tokenize_name_shorthand_error() -> None:
    """Test that & without name raises error."""
    with pytest.raises(TokenizerError) as exc_info:
        list(tokenize("&"))
    assert "Expected name after '&'" in str(exc_info.value)


# --- Name Filter Parser Tests ---


# --- Name Filter Canonicalization Tests ---


# --- Name Filter Evaluator Tests ---


def test_evaluate_name_match(
    make_changespec: Any,
) -> None:
    """Test name filter matches exactly."""
    query = parse_query("&my_feature")
    cs = make_changespec.create(name="my_feature")
    assert evaluate_query(query, cs) is True


# --- Sibling Filter Tokenizer Tests ---


# --- Sibling Filter Parser Tests ---


# --- Sibling Filter Canonicalization Tests ---


# --- Sibling Filter Evaluator Tests ---


def test_evaluate_sibling_combined_with_status(
    make_changespec: Any,
) -> None:
    """Test combining sibling and status filters."""
    query = parse_query("sibling:feature %d")
    cs1 = make_changespec.create(name="feature", status="Draft")
    assert evaluate_query(query, cs1) is True

    cs2 = make_changespec.create(name="feature__2", status="Draft")
    assert evaluate_query(query, cs2) is True

    cs3 = make_changespec.create(name="feature__3", status="Mailed")
    assert evaluate_query(query, cs3) is False

    cs4 = make_changespec.create(name="other_feature", status="Draft")
    assert evaluate_query(query, cs4) is False
