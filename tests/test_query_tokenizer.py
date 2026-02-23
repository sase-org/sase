"""Tests for the query language tokenizer."""

import pytest
from sase.ace.query.tokenizer import TokenizerError, TokenType, tokenize


def test_tokenize_not_keyword_with_error_suffix() -> None:
    """Test tokenizing 'NOT !!!' as NOT operator followed by ERROR_SUFFIX."""
    tokens = list(tokenize("NOT !!!"))
    assert tokens[0].type == TokenType.NOT
    assert tokens[0].value == "NOT"
    assert tokens[1].type == TokenType.ERROR_SUFFIX
    assert tokens[1].value == "!!!"


def test_tokenize_escape_sequences() -> None:
    """Test escape sequences in strings."""
    tokens = list(tokenize(r'"hello\nworld"'))
    assert tokens[0].value == "hello\nworld"

    tokens = list(tokenize(r'"say \"hi\""'))
    assert tokens[0].value == 'say "hi"'


def test_tokenize_bare_word_with_numbers() -> None:
    """Test tokenizing bare word with numbers."""
    tokens = list(tokenize("foo123"))
    assert tokens[0].type == TokenType.STRING
    assert tokens[0].value == "foo123"


def test_tokenize_at_not_standalone_is_error() -> None:
    """Test that @ followed by characters raises an error (@ must be standalone)."""
    with pytest.raises(TokenizerError) as exc_info:
        list(tokenize("@foo"))
    assert "Unexpected character" in str(exc_info.value)


def test_tokenize_triple_at() -> None:
    """Test tokenizing @@@ as RUNNING_AGENT."""
    tokens = list(tokenize("@@@"))
    assert len(tokens) == 2
    assert tokens[0].type == TokenType.RUNNING_AGENT
    assert tokens[0].value == "@@@"
    assert tokens[1].type == TokenType.EOF


def test_tokenize_standalone_at() -> None:
    """Test standalone @ at end tokenizes as RUNNING_AGENT."""
    tokens = list(tokenize("@"))
    assert len(tokens) == 2
    assert tokens[0].type == TokenType.RUNNING_AGENT
    assert tokens[0].value == "@"
    assert tokens[1].type == TokenType.EOF


def test_tokenize_not_at_with_space() -> None:
    """Test !@ followed by space tokenizes as NOT_RUNNING_AGENT."""
    tokens = list(tokenize('!@ "foo"'))
    assert tokens[0].type == TokenType.NOT_RUNNING_AGENT
    assert tokens[0].value == "!@"
    assert tokens[1].type == TokenType.STRING
    assert tokens[1].value == "foo"


def test_tokenize_double_exclamation_not_standalone() -> None:
    """Test !!"foo" tokenizes as NOT NOT STRING (not NOT_ERROR_SUFFIX)."""
    tokens = list(tokenize('!!"foo"'))
    assert tokens[0].type == TokenType.NOT
    assert tokens[1].type == TokenType.NOT
    assert tokens[2].type == TokenType.STRING
    assert tokens[2].value == "foo"
