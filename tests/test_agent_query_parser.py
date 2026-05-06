"""Tests for the agent query language parser."""

import pytest
from sase.ace.agent_query import (
    AgentQueryParseError,
    AndExpr,
    DurationCompare,
    NotExpr,
    OrExpr,
    PropertyMatch,
    StringMatch,
    parse_agent_query,
)


# --- Atoms -------------------------------------------------------------------


def test_parses_bare_word_as_string_match() -> None:
    assert parse_agent_query("foo") == StringMatch(value="foo", case_sensitive=False)


def test_parses_quoted_string() -> None:
    assert parse_agent_query('"hello world"') == StringMatch(
        value="hello world", case_sensitive=False
    )


def test_parses_case_sensitive_string() -> None:
    assert parse_agent_query('c"FAILED"') == StringMatch(
        value="FAILED", case_sensitive=True
    )


def test_parses_property_match() -> None:
    assert parse_agent_query("status:failed") == PropertyMatch(
        key="status", value="failed"
    )


def test_parses_dotted_tag_property_match() -> None:
    assert parse_agent_query("tag:sase-24.3") == PropertyMatch(
        key="tag", value="sase-24.3"
    )


def test_parses_age_comparisons() -> None:
    assert parse_agent_query("age>2h") == DurationCompare(
        key="age", op=">", seconds=7200
    )
    assert parse_agent_query("age<=15s") == DurationCompare(
        key="age", op="<=", seconds=15
    )
    # `age:N` is sugar for `age>=N`.
    assert parse_agent_query("age:1d") == DurationCompare(
        key="age", op=">=", seconds=86400
    )


# --- Boolean composition ----------------------------------------------------


def test_explicit_and() -> None:
    assert parse_agent_query("a AND b") == AndExpr(
        operands=[
            StringMatch(value="a", case_sensitive=False),
            StringMatch(value="b", case_sensitive=False),
        ]
    )


def test_implicit_and_via_juxtaposition() -> None:
    # Same AST as the explicit form.
    explicit = parse_agent_query("a AND b")
    implicit = parse_agent_query("a b")
    assert explicit == implicit


def test_or() -> None:
    assert parse_agent_query("a OR b") == OrExpr(
        operands=[
            StringMatch(value="a", case_sensitive=False),
            StringMatch(value="b", case_sensitive=False),
        ]
    )


def test_not_bang_and_word() -> None:
    bang = parse_agent_query("!foo")
    word = parse_agent_query("NOT foo")
    assert (
        bang == word == NotExpr(operand=StringMatch(value="foo", case_sensitive=False))
    )


# --- Precedence -------------------------------------------------------------


def test_not_binds_tighter_than_and() -> None:
    # `NOT a AND b` is `(NOT a) AND b`, not `NOT (a AND b)`.
    expr = parse_agent_query("NOT a AND b")
    assert expr == AndExpr(
        operands=[
            NotExpr(operand=StringMatch(value="a", case_sensitive=False)),
            StringMatch(value="b", case_sensitive=False),
        ]
    )


def test_and_binds_tighter_than_or() -> None:
    # `a OR b AND c` is `a OR (b AND c)`.
    expr = parse_agent_query("a OR b AND c")
    assert expr == OrExpr(
        operands=[
            StringMatch(value="a", case_sensitive=False),
            AndExpr(
                operands=[
                    StringMatch(value="b", case_sensitive=False),
                    StringMatch(value="c", case_sensitive=False),
                ]
            ),
        ]
    )


def test_parens_override_precedence() -> None:
    expr = parse_agent_query("(a OR b) AND c")
    assert expr == AndExpr(
        operands=[
            OrExpr(
                operands=[
                    StringMatch(value="a", case_sensitive=False),
                    StringMatch(value="b", case_sensitive=False),
                ]
            ),
            StringMatch(value="c", case_sensitive=False),
        ]
    )


def test_mixed_property_and_bare_word() -> None:
    expr = parse_agent_query('"database migration" status:failed')
    assert expr == AndExpr(
        operands=[
            StringMatch(value="database migration", case_sensitive=False),
            PropertyMatch(key="status", value="failed"),
        ]
    )


def test_complex_expression_with_property_and_age() -> None:
    expr = parse_agent_query("status:failed AND attention:true AND age>2h")
    assert expr == AndExpr(
        operands=[
            PropertyMatch(key="status", value="failed"),
            PropertyMatch(key="attention", value="true"),
            DurationCompare(key="age", op=">", seconds=7200),
        ]
    )


def test_not_distributes_over_parens() -> None:
    expr = parse_agent_query("NOT (project:foo OR cl:bar)")
    assert expr == NotExpr(
        operand=OrExpr(
            operands=[
                PropertyMatch(key="project", value="foo"),
                PropertyMatch(key="cl", value="bar"),
            ]
        )
    )


# --- Errors -----------------------------------------------------------------


def test_empty_query_errors() -> None:
    with pytest.raises(AgentQueryParseError) as exc:
        parse_agent_query("")
    assert "Empty" in str(exc.value)


def test_dangling_not_errors() -> None:
    # NOT with nothing after it (or NOT at EOF) must fail at parse time.
    with pytest.raises(AgentQueryParseError):
        parse_agent_query("NOT")
    with pytest.raises(AgentQueryParseError):
        parse_agent_query("!!!")


def test_unmatched_paren_errors() -> None:
    with pytest.raises(AgentQueryParseError):
        parse_agent_query("(a OR b")


def test_tokenizer_errors_surface_as_parse_errors() -> None:
    # Tokenizer errors should propagate as AgentQueryParseError (with position).
    with pytest.raises(AgentQueryParseError) as exc:
        parse_agent_query("zzz:foo")
    assert "Unknown property key" in str(exc.value)


def test_bool_value_must_be_true_or_false() -> None:
    with pytest.raises(AgentQueryParseError) as exc:
        parse_agent_query("pinned:yes")
    assert "true/false" in str(exc.value)
