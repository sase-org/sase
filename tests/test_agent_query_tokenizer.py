"""Tests for the agent query language tokenizer."""

import pytest
from sase.ace.agent_query.tokenizer import (
    BOOL_PROPERTY_KEYS,
    ENUM_PROPERTY_KEYS,
    SUBSTRING_PROPERTY_KEYS,
    TokenizerError,
    TokenType,
    tokenize,
)


def _types(query: str) -> list[TokenType]:
    return [t.type for t in tokenize(query)]


# --- Strings -----------------------------------------------------------------


def test_bare_word() -> None:
    tokens = list(tokenize("foo"))
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "foo"
    assert tokens[0].case_sensitive is False
    assert tokens[1].type == TokenType.EOF


def test_quoted_string_allows_spaces() -> None:
    tokens = list(tokenize('"database migration"'))
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "database migration"
    assert tokens[0].case_sensitive is False


def test_case_sensitive_string() -> None:
    tokens = list(tokenize('c"FAILED"'))
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "FAILED"
    assert tokens[0].case_sensitive is True


def test_escape_sequences() -> None:
    tokens = list(tokenize(r'"a\"b\nc"'))
    assert tokens[0].value == 'a"b\nc'


def test_unterminated_string_errors() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize('"oops'))
    assert "Unterminated string" in str(exc.value)


# --- Property keys -----------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SUBSTRING_PROPERTY_KEYS))
def test_substring_property_keys_round_trip(key: str) -> None:
    tokens = list(tokenize(f"{key}:foo"))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].property_key == key
    assert tokens[0].value == "foo"


@pytest.mark.parametrize("key", sorted(BOOL_PROPERTY_KEYS))
def test_bool_property_keys_accept_true_false(key: str) -> None:
    for v in ("true", "false", "TRUE", "False"):
        tokens = list(tokenize(f"{key}:{v}"))
        assert tokens[0].type == TokenType.PROPERTY
        assert tokens[0].property_key == key
        assert tokens[0].value == v.lower()


@pytest.mark.parametrize("key", sorted(BOOL_PROPERTY_KEYS))
def test_bool_property_keys_reject_other_values(key: str) -> None:
    for v in ("yes", "1", "on"):
        with pytest.raises(TokenizerError) as exc:
            list(tokenize(f"{key}:{v}"))
        assert "true/false" in str(exc.value)


@pytest.mark.parametrize("key,allowed", sorted(ENUM_PROPERTY_KEYS.items()))
def test_enum_property_keys(key: str, allowed: frozenset[str]) -> None:
    for v in allowed:
        tokens = list(tokenize(f"{key}:{v}"))
        assert tokens[0].type == TokenType.PROPERTY
        assert tokens[0].property_key == key
        assert tokens[0].value == v
    with pytest.raises(TokenizerError):
        list(tokenize(f"{key}:bogus"))


def test_unknown_property_key_rejected() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize("zzz:foo"))
    assert "Unknown property key" in str(exc.value)


def test_bare_tag_means_any_tagged_agent() -> None:
    tokens = list(tokenize("tag:"))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].property_key == "tag"
    assert tokens[0].value == ""

    # Even with trailing whitespace.
    tokens = list(tokenize("tag: "))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].property_key == "tag"
    assert tokens[0].value == ""


def test_property_value_can_be_quoted() -> None:
    tokens = list(tokenize('text:"hello world"'))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].property_key == "text"
    assert tokens[0].value == "hello world"


def test_property_value_can_be_dotted() -> None:
    tokens = list(tokenize("tag:sase-42.3"))
    assert tokens[0].type == TokenType.PROPERTY
    assert tokens[0].property_key == "tag"
    assert tokens[0].value == "sase-42.3"
    assert tokens[1].type == TokenType.EOF


# --- Duration / age ---------------------------------------------------------


@pytest.mark.parametrize(
    "query,op,seconds",
    [
        ("age>2h", ">", 7200),
        ("age<30m", "<", 1800),
        ("age>=1d", ">=", 86400),
        ("age<=15s", "<=", 15),
        ("age=1h", "=", 3600),
        ("age:2h", ">=", 7200),
    ],
)
def test_duration_literals(query: str, op: str, seconds: int) -> None:
    tokens = list(tokenize(query))
    assert tokens[0].type == TokenType.DURATION
    assert tokens[0].property_key == "age"
    assert tokens[0].duration_op == op
    assert tokens[0].duration_seconds == seconds


def test_duration_requires_unit() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize("age>5"))
    assert "duration unit" in str(exc.value)


def test_duration_rejects_composite_literal() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize("age>1h30m"))
    assert "Composite" in str(exc.value)


def test_age_requires_comparator() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize("age 2h"))
    assert "expected comparator" in str(exc.value)


def test_comparator_outside_age_is_rejected() -> None:
    with pytest.raises(TokenizerError) as exc:
        list(tokenize(">2h"))
    assert "comparison operators are only valid" in str(exc.value)


# --- Booleans / parens / not ------------------------------------------------


def test_keywords_and_parens() -> None:
    assert _types("a AND b") == [
        TokenType.STRING,
        TokenType.AND,
        TokenType.STRING,
        TokenType.EOF,
    ]
    assert _types("a OR b") == [
        TokenType.STRING,
        TokenType.OR,
        TokenType.STRING,
        TokenType.EOF,
    ]
    assert _types("NOT a") == [
        TokenType.NOT,
        TokenType.STRING,
        TokenType.EOF,
    ]
    assert _types("(a)") == [
        TokenType.LPAREN,
        TokenType.STRING,
        TokenType.RPAREN,
        TokenType.EOF,
    ]


def test_bang_is_not_operator() -> None:
    tokens = list(tokenize('!"foo"'))
    assert tokens[0].type == TokenType.NOT
    assert tokens[1].type == TokenType.STRING


def test_changespec_shorthand_is_rejected() -> None:
    # ChangeSpec sigils (status %d, project +, ancestor ^, sibling ~, name &,
    # running-agent @@@, running-process $$$, any-special *) are NOT carried
    # over to the agent query language — the tokenizer must error on them.
    for q in ("%d", "+proj", "^anc", "~sib", "&name", "@@@", "$$$", "*"):
        with pytest.raises(TokenizerError):
            list(tokenize(q))


def test_repeated_bang_is_just_repeated_not() -> None:
    # !!! used to be ChangeSpec error-suffix sugar; in agent-land it is just
    # three NOT operators. The tokenizer is happy; the parser will demand a
    # primary after the chain.
    tokens = list(tokenize("!!!"))
    assert [t.type for t in tokens[:-1]] == [TokenType.NOT] * 3
    assert tokens[-1].type == TokenType.EOF
