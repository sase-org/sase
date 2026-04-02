"""Tests for get_sole_project_filter utility."""

from sase.ace.query import get_sole_project_filter, parse_query


def test_single_project_filter() -> None:
    """project:foo returns 'foo'."""
    expr = parse_query("project:foo")
    assert get_sole_project_filter(expr) == "foo"


def test_project_shorthand() -> None:
    """+foo returns 'foo'."""
    expr = parse_query("+foo")
    assert get_sole_project_filter(expr) == "foo"


def test_project_with_status_and() -> None:
    """project:foo status:wip returns 'foo' (AND with non-project filter)."""
    expr = parse_query("project:foo status:wip")
    assert get_sole_project_filter(expr) == "foo"


def test_project_shorthand_with_status_shorthand() -> None:
    """+foo %w returns 'foo'."""
    expr = parse_query("+foo %w")
    assert get_sole_project_filter(expr) == "foo"


def test_no_project_filter() -> None:
    """Query without project filter returns None."""
    expr = parse_query("status:wip")
    assert get_sole_project_filter(expr) is None


def test_bare_string_no_project() -> None:
    """Bare string match returns None."""
    expr = parse_query("foobar")
    assert get_sole_project_filter(expr) is None


def test_multiple_project_filters() -> None:
    """project:a project:b returns None (ambiguous)."""
    expr = parse_query("project:a project:b")
    assert get_sole_project_filter(expr) is None


def test_negated_project_filter() -> None:
    """!project:foo returns None (negated)."""
    expr = parse_query("!project:foo")
    assert get_sole_project_filter(expr) is None


def test_project_inside_or() -> None:
    """project:a OR project:b returns None (OR branch)."""
    expr = parse_query("project:a OR project:b")
    assert get_sole_project_filter(expr) is None


def test_project_in_or_with_string() -> None:
    """project:foo OR bar returns None (inside OR)."""
    expr = parse_query("project:foo OR bar")
    assert get_sole_project_filter(expr) is None


def test_project_and_negated_project() -> None:
    """project:foo !project:bar — only foo counts (bar is negated)."""
    expr = parse_query("project:foo !project:bar")
    assert get_sole_project_filter(expr) == "foo"
