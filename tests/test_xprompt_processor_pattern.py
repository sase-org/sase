"""Tests for _XPROMPT_PATTERN regex matching."""

import re

from sase.xprompt.processor import _XPROMPT_PATTERN


def test_xprompt_pattern_simple_name() -> None:
    """Test that simple xprompt names match."""
    match = re.search(_XPROMPT_PATTERN, "#foo")
    assert match is not None
    assert match.group(1) == "foo"


def test_xprompt_pattern_with_underscore() -> None:
    """Test that xprompt names with underscores match."""
    match = re.search(_XPROMPT_PATTERN, "#foo_bar")
    assert match is not None
    assert match.group(1) == "foo_bar"


def test_xprompt_pattern_with_numbers() -> None:
    """Test that xprompt names with numbers match."""
    match = re.search(_XPROMPT_PATTERN, "#foo123")
    assert match is not None
    assert match.group(1) == "foo123"


def test_xprompt_pattern_namespaced_single() -> None:
    """Test that single-level namespaced xprompts match."""
    match = re.search(_XPROMPT_PATTERN, "#mentor/aaa")
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_xprompt_pattern_namespaced_multi() -> None:
    """Test that multi-level namespaced xprompts match."""
    match = re.search(_XPROMPT_PATTERN, "#foo/bar/baz")
    assert match is not None
    assert match.group(1) == "foo/bar/baz"


def test_xprompt_pattern_namespaced_with_underscore() -> None:
    """Test that namespaced xprompts with underscores match."""
    match = re.search(_XPROMPT_PATTERN, "#my_namespace/my_xprompt")
    assert match is not None
    assert match.group(1) == "my_namespace/my_xprompt"


def test_xprompt_pattern_namespaced_with_numbers() -> None:
    """Test that namespaced xprompts with numbers match."""
    match = re.search(_XPROMPT_PATTERN, "#ns1/prompt2")
    assert match is not None
    assert match.group(1) == "ns1/prompt2"


def test_xprompt_pattern_namespaced_with_args() -> None:
    """Test that namespaced xprompts with parentheses match."""
    match = re.search(_XPROMPT_PATTERN, "#mentor/aaa(arg1)")
    assert match is not None
    assert match.group(1) == "mentor/aaa"
    assert match.group(2) == "("  # Open paren captured


def test_xprompt_pattern_namespaced_with_colon_arg() -> None:
    """Test that namespaced xprompts with colon args match."""
    match = re.search(_XPROMPT_PATTERN, "#foo/bar:value")
    assert match is not None
    assert match.group(1) == "foo/bar"
    assert match.group(3) == "value"


def test_xprompt_pattern_namespaced_with_plus() -> None:
    """Test that namespaced xprompts with plus suffix match."""
    match = re.search(_XPROMPT_PATTERN, "#foo/bar+")
    assert match is not None
    assert match.group(1) == "foo/bar"
    assert match.group(4) == "+"


def test_xprompt_pattern_after_whitespace() -> None:
    """Test that xprompts match after whitespace."""
    match = re.search(_XPROMPT_PATTERN, "text #mentor/aaa")
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_xprompt_pattern_at_start() -> None:
    """Test that xprompts match at start of string."""
    match = re.search(_XPROMPT_PATTERN, "#mentor/aaa text")
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_xprompt_pattern_after_open_paren() -> None:
    """Test that xprompts match after open parenthesis."""
    match = re.search(_XPROMPT_PATTERN, "(#mentor/aaa)")
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_xprompt_pattern_after_quote() -> None:
    """Test that xprompts match after quote."""
    match = re.search(_XPROMPT_PATTERN, '"#mentor/aaa"')
    assert match is not None
    assert match.group(1) == "mentor/aaa"


def test_xprompt_pattern_colon_arg_strips_trailing_period() -> None:
    """Test that trailing period is not captured in colon arg."""
    match = re.search(_XPROMPT_PATTERN, "#clr:832098883.")
    assert match is not None
    assert match.group(1) == "clr"
    assert match.group(3) == "832098883"


def test_xprompt_pattern_not_after_letter() -> None:
    """Test that xprompts don't match after letter (e.g., C#)."""
    match = re.search(_XPROMPT_PATTERN, "C#mentor")
    assert match is None


def test_xprompt_pattern_not_double_slash() -> None:
    """Test that double slashes don't match (invalid namespace)."""
    match = re.search(_XPROMPT_PATTERN, "#foo//bar")
    assert match is not None
    # Should only match #foo, not #foo//bar
    assert match.group(1) == "foo"


def test_xprompt_pattern_not_leading_slash() -> None:
    """Test that leading slash doesn't match."""
    match = re.search(_XPROMPT_PATTERN, "#/foo")
    assert match is None


def test_xprompt_pattern_not_trailing_slash() -> None:
    """Test that trailing slash is not part of the match."""
    match = re.search(_XPROMPT_PATTERN, "#foo/")
    assert match is not None
    # Should only match #foo, the trailing slash is not valid namespace
    assert match.group(1) == "foo"


# --- Command substitution in pattern matching ---


def test_xprompt_pattern_colon_arg_command_substitution() -> None:
    """Test that #bug:$(branch_bug) captures $(branch_bug) as colon arg."""
    match = re.search(_XPROMPT_PATTERN, "#bug:$(branch_bug)")
    assert match is not None
    assert match.group(1) == "bug"
    assert match.group(3) == "$(branch_bug)"


def test_xprompt_pattern_colon_arg_cmd_sub_trailing_punctuation() -> None:
    """Test that trailing punctuation after $(cmd) is not captured."""
    match = re.search(_XPROMPT_PATTERN, "#bug:$(branch_bug)?")
    assert match is not None
    assert match.group(1) == "bug"
    assert match.group(3) == "$(branch_bug)"


def test_xprompt_pattern_colon_arg_cmd_sub_with_args() -> None:
    """Test that $(cmd arg) is captured as colon arg."""
    match = re.search(_XPROMPT_PATTERN, "#foo:$(echo hello)")
    assert match is not None
    assert match.group(1) == "foo"
    assert match.group(3) == "$(echo hello)"


# --- Multi-arg colon syntax ---


def test_xprompt_pattern_colon_multi_arg() -> None:
    """Test that #foo:a,b,c captures the full comma-separated string."""
    match = re.search(_XPROMPT_PATTERN, "#foo:a,b,c")
    assert match is not None
    assert match.group(1) == "foo"
    assert match.group(3) == "a,b,c"


def test_xprompt_pattern_colon_trailing_comma() -> None:
    """Test that trailing comma is excluded from the match."""
    match = re.search(_XPROMPT_PATTERN, "#foo:a,")
    assert match is not None
    assert match.group(1) == "foo"
    assert match.group(3) == "a"


# --- Double-underscore as slash alias ---


def test_xprompt_pattern_double_underscore_matches() -> None:
    """Test that double underscores in xprompt names are matched by the pattern."""
    match = re.search(_XPROMPT_PATTERN, "#foo__bar")
    assert match is not None
    assert match.group(1) == "foo__bar"


def test_xprompt_pattern_double_underscore_multi_level() -> None:
    """Test that multiple double underscores are matched."""
    match = re.search(_XPROMPT_PATTERN, "#a__b__c")
    assert match is not None
    assert match.group(1) == "a__b__c"


def test_xprompt_pattern_double_underscore_with_args() -> None:
    """Test that double-underscore names work with parenthesis args."""
    match = re.search(_XPROMPT_PATTERN, "#foo__bar(arg)")
    assert match is not None
    assert match.group(1) == "foo__bar"
    assert match.group(2) == "("
