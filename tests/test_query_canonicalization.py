"""Tests for query canonicalization (converting parsed queries to canonical string form)."""

from sase.ace.query import parse_query, to_canonical_string


def test_canonical_case_sensitive_string() -> None:
    """Test canonicalization of case-sensitive string."""
    result = parse_query('c"Foo"')
    assert to_canonical_string(result) == 'c"Foo"'


def test_canonical_not() -> None:
    """Test canonicalization of NOT expression."""
    result = parse_query('!"foo"')
    assert to_canonical_string(result) == 'NOT "foo"'


def test_canonical_any_special_implicit_and() -> None:
    """Test canonicalization of * with implicit AND."""
    result = parse_query('* "foo"')
    assert to_canonical_string(result) == '(!!! OR @@@ OR $$$) AND "foo"'
