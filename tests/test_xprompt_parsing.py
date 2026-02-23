"""Tests for xprompt._parsing functions."""

from sase.xprompt._parsing import (
    _preprocess_paren_shorthand,
    find_matching_paren_for_args,
    parse_workflow_reference,
    preprocess_shorthand_syntax,
    strip_hitl_suffix,
)


# Tests for _process_text_block


# Tests for _find_shorthand_text_end


# Tests for preprocess_shorthand_syntax


# Tests for find_matching_paren_for_args


def test_find_matching_paren_not_at_paren() -> None:
    """Test find_matching_paren_for_args returns None when not at paren."""
    assert find_matching_paren_for_args("hello", 0) is None


def test_find_matching_paren_with_text_block() -> None:
    """Test find_matching_paren_for_args handles text blocks."""
    assert find_matching_paren_for_args("([[content]]))", 0) == 12


# Tests for _parse_named_arg


# Tests for parse_args


# Tests for parse_workflow_reference


def test_parse_workflow_reference_plus() -> None:
    """Test parse_workflow_reference with plus syntax."""
    name, pos, _ = parse_workflow_reference("myworkflow+")
    assert name == "myworkflow"
    assert pos == ["true"]


def test_parse_workflow_reference_paren() -> None:
    """Test parse_workflow_reference with parenthesis syntax."""
    name, pos, named = parse_workflow_reference('myworkflow(a, key="b")')
    assert name == "myworkflow"
    assert pos == ["a"]
    assert named == {"key": "b"}


# Tests for _format_as_text_block


# Tests for _preprocess_paren_shorthand


def test_paren_shorthand_multiline_double_newline() -> None:
    """Test paren shorthand with multiline text terminated by \\n\\n."""
    result = _preprocess_paren_shorthand("#test(arg1): line1\nline2\n\nother", {"test"})
    assert result == "#test(arg1, [[line1\n  line2]])\n\nother"


def test_paren_shorthand_unknown_name() -> None:
    """Test unknown names are not processed."""
    prompt = "#unknown(arg): hello"
    result = _preprocess_paren_shorthand(prompt, {"test"})
    assert result == "#unknown(arg): hello"


# Tests for _find_double_colon_text_end


# Tests for simple double-colon shorthand


def test_double_colon_shorthand_terminated_by_next_directive() -> None:
    """Test double-colon text ends at the next directive."""
    prompt = "#foo:: line1\n\nline3\n#bar: other"
    result = preprocess_shorthand_syntax(prompt, {"foo", "bar"})
    assert result == "#foo([[line1\n\n  line3]])\n#bar([[other]])"


def test_double_colon_shorthand_unknown_name_ignored() -> None:
    """Test that unknown names are not processed for double-colon."""
    prompt = "#unknown:: some text"
    result = preprocess_shorthand_syntax(prompt, {"foo"})
    assert result == "#unknown:: some text"


# Tests for strip_hitl_suffix


def test_strip_hitl_suffix_double_bang() -> None:
    """Test strip_hitl_suffix with !! suffix returns True."""
    ref, override = strip_hitl_suffix("foo!!")
    assert ref == "foo"
    assert override is True


def test_strip_hitl_suffix_question_with_paren_args() -> None:
    """Test strip_hitl_suffix ?? with parenthesis args."""
    ref, override = strip_hitl_suffix("foo??(a, b)")
    assert ref == "foo(a, b)"
    assert override is False


# Tests for paren double-colon shorthand


def test_paren_double_colon_shorthand_empty_parens() -> None:
    """Test #name():: text → #name([[text]])."""
    result = _preprocess_paren_shorthand("#test():: hello world", {"test"})
    assert result == "#test([[hello world]])"


# Tests for mixed directives


# Tests for strip_vcs_workflow_tag
