"""Tests for shorthand syntax parsing (#foo: text and #foo:: text)."""

import re

from sase.xprompt._parsing import (
    DOUBLE_COLON_SHORTHAND_PATTERN,
    SHORTHAND_PATTERN,
    _find_shorthand_text_end,
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


def test_shorthand_pattern_not_mid_line() -> None:
    """Test that shorthand pattern doesn't match mid-line."""
    match = re.search(SHORTHAND_PATTERN, "text #foo: bar")
    assert match is None


def test_shorthand_pattern_requires_space_after_colon() -> None:
    """Test that pattern requires space after colon (distinguishes from :arg)."""
    # Without space - should not match shorthand pattern
    match = re.search(SHORTHAND_PATTERN, "#foo:bar")
    assert match is None


def testfind_shorthand_text_end_at_blank_line() -> None:
    """Test finding end at blank line."""
    prompt = "some text here\n\nmore text"
    end = _find_shorthand_text_end(prompt, 0)
    assert end == 14
    assert prompt[end : end + 2] == "\n\n"


def testfind_shorthand_text_end_at_eof() -> None:
    """Test finding end at end of string."""
    prompt = "no blank line here"
    end = _find_shorthand_text_end(prompt, 0)
    assert end == len(prompt)


def test_preprocess_shorthand_single_line() -> None:
    """Test preprocessing single-line shorthand."""
    prompt = "#foo: simple text"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    assert result == "#foo([[simple text]])"


def test_preprocess_shorthand_multiline_until_blank() -> None:
    """Test preprocessing multi-line shorthand until blank line."""
    prompt = "#foo: line one\nline two\n\nother text"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    assert result == "#foo([[line one\n  line two]])\n\nother text"


def test_preprocess_shorthand_multiline_until_eof() -> None:
    """Test preprocessing multi-line shorthand until end of string."""
    prompt = "#foo: line one\nline two\nline three"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    assert result == "#foo([[line one\n  line two\n  line three]])"


def test_preprocess_shorthand_unknown_name_unchanged() -> None:
    """Test that unknown xprompt names are not processed."""
    prompt = "#unknown: some text"
    result = preprocess_shorthand_syntax(prompt, {"foo", "bar"})
    assert result == "#unknown: some text"


def test_preprocess_shorthand_namespaced() -> None:
    """Test preprocessing namespaced xprompt shorthand."""
    prompt = "#mentor/aaa: review this code"
    result = preprocess_shorthand_syntax(prompt, {"mentor/aaa"})
    assert result == "#mentor/aaa([[review this code]])"


def test_preprocess_shorthand_multiple_in_prompt() -> None:
    """Test preprocessing multiple shorthands in one prompt."""
    prompt = "#foo: text one\n\n#bar: text two"
    result = preprocess_shorthand_syntax(prompt, {"foo", "bar"})
    assert result == "#foo([[text one]])\n\n#bar([[text two]])"


def test_preprocess_shorthand_not_at_line_start() -> None:
    """Test that shorthand mid-line is not processed."""
    prompt = "Use #foo: inline"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    # Should remain unchanged because #foo: is not at line start
    assert result == "Use #foo: inline"


def test_preprocess_shorthand_preserves_trailing_content() -> None:
    """Test that content after blank line terminator is preserved."""
    # \n\n terminates the shorthand, third \n and "more text" are preserved
    prompt = "#foo: line one\n\n\nmore text"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    # Should end at first \n\n, keeping the trailing \n before "more text"
    assert result == "#foo([[line one]])\n\n\nmore text"


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
