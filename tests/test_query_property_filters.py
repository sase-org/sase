"""Tests for property filter functionality in the query language."""

from typing import Any

import pytest
from sase.ace.query import (
    evaluate_query,
    parse_query,
    to_canonical_string,
)
from sase.ace.query.tokenizer import TokenizerError, TokenType, tokenize

# --- Tokenizer Tests ---


def test_tokenize_status_shorthand_invalid() -> None:
    """Test that %x raises error for invalid status shorthand."""
    with pytest.raises(TokenizerError) as exc_info:
        list(tokenize("%x"))
    assert "Invalid status shorthand" in str(exc_info.value)


def test_tokenize_property_with_quoted_value() -> None:
    """Test tokenizing property with quoted value."""
    tokens = list(tokenize('status:"my status"'))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].value == "my status"
    assert tokens[0].property_key == "status"


def test_tokenize_invalid_property_key() -> None:
    """Test that unknown property key raises error."""
    with pytest.raises(TokenizerError) as exc_info:
        list(tokenize("unknown:value"))
    assert "Unknown property key" in str(exc_info.value)


# --- Parser Tests ---


# --- Canonicalization Tests ---


def test_canonical_status_property() -> None:
    """Test canonicalization of status property."""
    result = parse_query("%d")
    assert to_canonical_string(result) == "status:DRAFT"


# --- Evaluator Tests ---


def test_evaluate_project_match(
    make_changespec: Any,
) -> None:
    """Test project filter matches project basename."""
    query = parse_query("+myproject")
    cs = make_changespec.create(
        file_path="/home/user/.sase/projects/myproject/myproject.gp"
    )
    assert evaluate_query(query, cs) is True


def test_evaluate_ancestor_no_match(
    make_changespec: Any,
) -> None:
    """Test ancestor filter does not match unrelated ChangeSpec."""
    query = parse_query("^unrelated")
    cs = make_changespec.create(name="feature", parent="different_parent")
    all_cs = [cs]
    assert evaluate_query(query, cs, all_cs) is False


def test_evaluate_ancestor_without_all_changespecs(
    make_changespec: Any,
) -> None:
    """Test ancestor filter returns False when all_changespecs is None."""
    query = parse_query("^parent")
    cs = make_changespec.create(name="feature", parent="parent")
    # all_changespecs=None (default)
    assert evaluate_query(query, cs) is False


def test_evaluate_ancestor_handles_cycle(
    make_changespec: Any,
) -> None:
    """Test ancestor filter handles cycles without infinite loop."""
    query = parse_query("^unrelated")
    # Create a cycle: A -> B -> A
    cs_a = make_changespec.create(name="A", parent="B")
    cs_b = make_changespec.create(name="B", parent="A")
    all_cs = [cs_a, cs_b]
    # Should not hang, should return False since "unrelated" is not in the cycle
    assert evaluate_query(query, cs_a, all_cs) is False


# --- Integration Tests ---


def test_full_pipeline_ancestor_chain(
    make_changespec: Any,
) -> None:
    """Test full pipeline with ancestor filter on parent chain."""
    parent = make_changespec.create(name="parent_feature")
    child = make_changespec.create(name="child_feature", parent="parent_feature")
    grandchild = make_changespec.create(name="grandchild", parent="child_feature")
    unrelated = make_changespec.create(name="unrelated_feature")

    all_cs = [parent, child, grandchild, unrelated]

    query = parse_query("^parent_feature")
    results = [cs for cs in all_cs if evaluate_query(query, cs, all_cs)]

    # Should match: parent (name match), child (parent match), grandchild (grandparent)
    # Should NOT match: unrelated
    assert len(results) == 3
    names = [cs.name for cs in results]
    assert "parent_feature" in names
    assert "child_feature" in names
    assert "grandchild" in names
    assert "unrelated_feature" not in names
