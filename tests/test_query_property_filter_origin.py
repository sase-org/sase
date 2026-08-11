"""Tests for the origin: property filter in the query language."""

from typing import Any

from sase.ace.query import evaluate_query, parse_query
from sase.ace.query.searchable import get_searchable_text
from sase.ace.query.tokenizer import TokenType, tokenize

# --- Origin Filter Tokenizer Tests ---


def test_tokenize_origin_property() -> None:
    """Test tokenizing origin:external as a PROPERTY token."""
    tokens = list(tokenize("origin:external"))
    assert len(tokens) == 2
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].value == "external"
    assert tokens[0].property_key == "origin"


# --- Origin Filter Evaluator Tests ---


def test_evaluate_origin_external_match(make_patch: Any) -> None:
    """Test origin:external matches a Patch with PR_ORIGIN=external."""
    query = parse_query("origin:external")
    cs = make_patch.create(pr_origin="external")
    assert evaluate_query(query, cs) is True


def test_evaluate_origin_sase_match(make_patch: Any) -> None:
    """Test origin:sase matches a Patch with PR_ORIGIN=sase."""
    query = parse_query("origin:sase")
    cs = make_patch.create(pr_origin="sase")
    assert evaluate_query(query, cs) is True
    assert evaluate_query(query, make_patch.create(pr_origin="external")) is False


def test_evaluate_origin_unknown_default(make_patch: Any) -> None:
    """A Patch with no PR_ORIGIN normalizes to unknown and matches origin:unknown."""
    query = parse_query("origin:unknown")
    cs = make_patch.create()
    assert evaluate_query(query, cs) is True


def test_evaluate_origin_case_insensitive(make_patch: Any) -> None:
    """origin: matches case-insensitively."""
    query = parse_query("origin:EXTERNAL")
    assert evaluate_query(query, make_patch.create(pr_origin="external")) is True


def test_evaluate_origin_combined_with_status(make_patch: Any) -> None:
    """origin: composes with other filters via implicit AND."""
    query = parse_query("origin:external %m")
    cs1 = make_patch.create(pr_origin="external", status="Mailed")
    assert evaluate_query(query, cs1) is True

    cs2 = make_patch.create(pr_origin="sase", status="Mailed")
    assert evaluate_query(query, cs2) is False


def test_get_searchable_text_includes_pr_origin(make_patch: Any) -> None:
    """Bare-word string search can find Patches by their normalized origin."""
    cs = make_patch.create(pr_origin="external")
    assert "external" in get_searchable_text(cs)
