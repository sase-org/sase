"""Tests for shorthand syntax parsing (#foo: text and #foo:: text)."""

import re

from sase.xprompt._parsing import (
    DOUBLE_COLON_SHORTHAND_PATTERN,
    SHORTHAND_PATTERN,
    preprocess_shorthand_syntax,
)


# --- Shorthand syntax tests ---


def test_shorthand_pattern_at_start_of_string() -> None:
    """Test that shorthand pattern matches at start of string."""
    match = re.search(SHORTHAND_PATTERN, "#foo: some text")
    assert match is not None
    assert match.group(1) == "foo"


def test_shorthand_pattern_after_newline() -> None:
    """Test that shorthand pattern matches after newline."""
    match = re.search(SHORTHAND_PATTERN, "prefix\n#bar: text here")
    assert match is not None
    assert match.group(1) == "bar"


def test_shorthand_pattern_namespaced() -> None:
    """Test that shorthand pattern matches namespaced xprompts."""
    match = re.search(SHORTHAND_PATTERN, "#mentor/aaa: some text")
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_shorthand_pattern_mid_line_after_space() -> None:
    """Test that shorthand pattern matches mid-line after a space."""
    match = re.search(SHORTHAND_PATTERN, "text #foo: bar")
    assert match is not None
    assert match.group(1) == "foo"


def test_shorthand_pattern_mid_line_after_open_paren() -> None:
    """Test that shorthand pattern matches mid-line after '('."""
    match = re.search(SHORTHAND_PATTERN, "(#foo: bar")
    assert match is not None
    assert match.group(1) == "foo"


def test_shorthand_pattern_mid_line_after_double_quote() -> None:
    """Test that shorthand pattern matches mid-line after '\"'."""
    match = re.search(SHORTHAND_PATTERN, '"#foo: bar')
    assert match is not None
    assert match.group(1) == "foo"


def test_shorthand_pattern_not_mid_line_after_letter() -> None:
    """Test that shorthand pattern doesn't match mid-line after a letter."""
    match = re.search(SHORTHAND_PATTERN, "x#foo: bar")
    assert match is None


def test_double_colon_shorthand_pattern_mid_line_after_space() -> None:
    """Test that DOUBLE_COLON_SHORTHAND_PATTERN matches mid-line after a space."""
    match = re.search(DOUBLE_COLON_SHORTHAND_PATTERN, "text #foo:: bar")
    assert match is not None
    assert match.group(1) == "foo"


def test_shorthand_pattern_requires_space_after_colon() -> None:
    """Test that pattern requires space after colon (distinguishes from :arg)."""
    # Without space - should not match shorthand pattern
    match = re.search(SHORTHAND_PATTERN, "#foo:bar")
    assert match is None


def test_preprocess_shorthand_unknown_name_unchanged() -> None:
    """Test that unknown xprompt names are not processed."""
    prompt = "#unknown: some text"
    result = preprocess_shorthand_syntax(prompt, {"foo", "bar"})
    assert result == "#unknown: some text"


# --- Double-colon shorthand pattern tests ---


def test_double_colon_shorthand_pattern_at_start() -> None:
    """Test that DOUBLE_COLON_SHORTHAND_PATTERN matches at start of string."""
    match = re.search(DOUBLE_COLON_SHORTHAND_PATTERN, "#foo:: some text")
    assert match is not None
    assert match.group(1) == "foo"


def test_double_colon_shorthand_pattern_not_single_colon() -> None:
    """Test that DOUBLE_COLON_SHORTHAND_PATTERN does NOT match single colon."""
    match = re.search(DOUBLE_COLON_SHORTHAND_PATTERN, "#foo: some text")
    assert match is None


def test_preprocess_shorthand_mid_line_after_space() -> None:
    """Test preprocess_shorthand_syntax converts mid-line shorthand after space."""
    result = preprocess_shorthand_syntax("expanded text #mentor: help me", {"mentor"})
    assert result == "expanded text #mentor([[help me]])"


def test_preprocess_shorthand_mid_line_after_newline_content() -> None:
    """Test preprocess_shorthand_syntax converts shorthand appearing after expanded content."""
    result = preprocess_shorthand_syntax(
        "some expanded xprompt content #foo: bar baz", {"foo"}
    )
    assert result == "some expanded xprompt content #foo([[bar baz]])"
