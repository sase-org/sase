"""Tests for xprompt._parsing core parsing helpers."""

import pytest

from sase.xprompt._parsing import (
    _preprocess_paren_shorthand,
    find_matching_paren_for_args,
    parse_args,
    parse_workflow_reference,
    preprocess_shorthand_syntax,
    strip_hitl_suffix,
)


def test_find_matching_paren_not_at_paren() -> None:
    """Test find_matching_paren_for_args returns None when not at paren."""
    assert find_matching_paren_for_args("hello", 0) is None


def test_find_matching_paren_with_text_block() -> None:
    """Test find_matching_paren_for_args handles text blocks."""
    assert find_matching_paren_for_args("([[content]]))", 0) == 12


def test_find_matching_paren_with_inner_text_block_marker() -> None:
    """Text blocks close only when ``]]`` reaches an argument boundary."""
    prose = (
        "Use `[<web>:<keyword> [...]]` for example, then keep "
        "the following comma inside the same argument."
    )
    source = f"#research_swarm([[{prose}]], wait=ready)"
    open_paren = source.index("(")
    close_paren = find_matching_paren_for_args(source, open_paren)

    assert close_paren == len(source) - 1
    positional, named = parse_args(source[open_paren + 1 : close_paren])
    assert positional == [prose]
    assert named == {"wait": "ready"}


def test_parse_args_text_block_ignores_non_terminating_marker() -> None:
    """A ``]]`` followed by prose remains part of the text block."""
    positional, named = parse_args("[[a [b [c]] d, e]]")

    assert positional == ["a [b [c]] d, e"]
    assert named == {}


def test_parse_args_text_block_closes_after_content_bracket() -> None:
    """A content-ending ``]`` may overlap the real closing ``]]`` marker."""
    positional, named = parse_args("summary=[[[bold]Research[/bold]]]")

    assert positional == []
    assert named == {"summary": "[bold]Research[/bold]"}


@pytest.mark.parametrize(
    ("source", "expected_positional", "expected_named"),
    [
        ("[[a]], [[b]]", ["a", "b"], {}),
        ("foo=[[a]], bar=1", [], {"foo": "a", "bar": "1"}),
        ("[[x, y]]", ["x, y"], {}),
    ],
)
def test_parse_args_text_block_compatibility_cases(
    source: str,
    expected_positional: list[str],
    expected_named: dict[str, str],
) -> None:
    """Existing well-formed text-block argument shapes keep parsing."""
    positional, named = parse_args(source)

    assert positional == expected_positional
    assert named == expected_named


def test_parse_args_decodes_plus_space_substitution() -> None:
    """Application+Support is decoded in positional and named values."""
    positional, named = parse_args(
        "/Users/me/Library/Application+Support/sase, root=/tmp/Application+Support"
    )

    assert positional == ["/Users/me/Library/Application Support/sase"]
    assert named == {"root": "/tmp/Application Support"}


def test_parse_workflow_reference_plus() -> None:
    """Test parse_workflow_reference with plus syntax."""
    name, pos, _ = parse_workflow_reference("myworkflow+")
    assert name == "myworkflow"
    assert pos == ["true"]


def test_parse_workflow_reference_colon_decodes_plus_space_substitution() -> None:
    """Test parse_workflow_reference decodes plus substitution in colon args."""
    name, pos, named = parse_workflow_reference(
        "myworkflow:/Users/me/Library/Application+Support/sase"
    )
    assert name == "myworkflow"
    assert pos == ["/Users/me/Library/Application Support/sase"]
    assert named == {}


def test_parse_workflow_reference_paren() -> None:
    """Test parse_workflow_reference with parenthesis syntax."""
    name, pos, named = parse_workflow_reference('myworkflow(a, key="b")')
    assert name == "myworkflow"
    assert pos == ["a"]
    assert named == {"key": "b"}


def test_parse_workflow_reference_paren_decodes_plus_space_substitution() -> None:
    """Test parse_workflow_reference decodes plus substitution in paren args."""
    name, pos, named = parse_workflow_reference(
        "myworkflow(/Users/me/Library/Application+Support/sase, root=/tmp/Application+Support)"
    )
    assert name == "myworkflow"
    assert pos == ["/Users/me/Library/Application Support/sase"]
    assert named == {"root": "/tmp/Application Support"}


def test_paren_shorthand_multiline_double_newline() -> None:
    """Test paren shorthand with multiline text terminated by \\n\\n."""
    result = _preprocess_paren_shorthand("#test(arg1): line1\nline2\n\nother", {"test"})
    assert result == "#test(arg1, [[line1\n  line2]])\n\nother"


def test_paren_shorthand_unknown_name() -> None:
    """Test unknown names are not processed."""
    prompt = "#unknown(arg): hello"
    result = _preprocess_paren_shorthand(prompt, {"test"})
    assert result == "#unknown(arg): hello"


def test_paren_shorthand_mid_line() -> None:
    """Test paren shorthand matches mid-line after a space."""
    result = _preprocess_paren_shorthand("expanded #test(arg1): hello world", {"test"})
    assert result == "expanded #test(arg1, [[hello world]])"


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


def test_paren_double_colon_shorthand_empty_parens() -> None:
    """Test #name():: text -> #name([[text]])."""
    result = _preprocess_paren_shorthand("#test():: hello world", {"test"})
    assert result == "#test([[hello world]])"
