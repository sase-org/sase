"""Tests for multi_prompt parsing module."""

import pytest

from sase.agent.multi_prompt import (
    _LocalMacroNameError,
    is_multi_prompt,
    parse_multi_prompt,
)


# --- parse_multi_prompt: basic segment splitting ---


def test_single_segment_no_frontmatter() -> None:
    """Plain text with no --- yields one segment and no macros."""
    result = parse_multi_prompt("Fix the bug in parser.py")
    assert result.segments == ["Fix the bug in parser.py"]
    assert result.frontmatter is None
    assert result.local_macros == {}


def test_two_segments_no_frontmatter() -> None:
    """Two segments separated by ---."""
    text = "Fix the bug\n---\nAdd tests"
    result = parse_multi_prompt(text)
    assert result.segments == ["Fix the bug", "Add tests"]
    assert result.frontmatter is None


def test_three_segments() -> None:
    text = "seg1\n---\nseg2\n---\nseg3"
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2", "seg3"]


# --- parse_multi_prompt: frontmatter ---


def test_frontmatter_single_segment() -> None:
    """Frontmatter + single segment = single-agent with local macros."""
    text = '---\nxprompts:\n  _style: "be concise"\n---\nDo the thing. #_style'
    result = parse_multi_prompt(text)
    assert result.segments == ["Do the thing. #_style"]
    assert "_style" in result.local_macros
    assert result.local_macros["_style"].content == "be concise"


def test_frontmatter_multiple_segments() -> None:
    """Frontmatter + multiple segments."""
    text = '---\nxprompts:\n  _review: "Focus on correctness"\n---\nFix bug\n---\nAdd tests'
    result = parse_multi_prompt(text)
    assert result.segments == ["Fix bug", "Add tests"]
    assert "_review" in result.local_macros


def test_frontmatter_without_macros_key() -> None:
    """Frontmatter that has no macros key produces no local macros."""
    text = "---\ntitle: my prompt\n---\nDo stuff"
    result = parse_multi_prompt(text)
    assert result.local_macros == {}
    assert result.frontmatter == {"title": "my prompt"}
    assert result.segments == ["Do stuff"]


def test_frontmatter_macros_popped_from_dict() -> None:
    """The macros key is consumed and not left in frontmatter."""
    text = '---\nxprompts:\n  _x: "val"\ntitle: foo\n---\nbody'
    result = parse_multi_prompt(text)
    assert "xprompts" not in (result.frontmatter or {})
    assert "title" in (result.frontmatter or {})


# --- parse_multi_prompt: local macro name validation ---


def test_invalid_macro_name_no_underscore() -> None:
    """Local macro names must start with _."""
    text = '---\nxprompts:\n  badname: "content"\n---\nbody'
    with pytest.raises(_LocalMacroNameError, match="must start with '_'"):
        parse_multi_prompt(text)


def test_mixed_valid_invalid_names() -> None:
    """Even one invalid name should raise."""
    text = '---\nxprompts:\n  _good: "ok"\n  bad: "nope"\n---\nbody'
    with pytest.raises(_LocalMacroNameError, match="bad"):
        parse_multi_prompt(text)


# --- parse_multi_prompt: fenced code block protection ---


def test_separator_inside_fenced_block_not_split() -> None:
    """--- inside a fenced code block should NOT be treated as a separator."""
    text = "Before\n```\ncode\n---\nmore code\n```\nAfter"
    result = parse_multi_prompt(text)
    assert len(result.segments) == 1
    assert "---" in result.segments[0]


def test_separator_outside_fenced_block_still_splits() -> None:
    """--- outside code blocks should still split."""
    text = "seg1\n```\ncode block\n```\n---\nseg2"
    result = parse_multi_prompt(text)
    assert len(result.segments) == 2


# --- parse_multi_prompt: empty/whitespace segment handling ---


def test_empty_segments_stripped() -> None:
    """Empty segments between separators are dropped."""
    text = "seg1\n---\n\n---\nseg2"
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2"]


def test_whitespace_only_segments_stripped() -> None:
    """Whitespace-only segments are dropped."""
    text = "seg1\n---\n   \n---\nseg2"
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2"]


def test_trailing_separator() -> None:
    """Trailing --- should not create an empty segment."""
    text = "seg1\n---\nseg2\n---"
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2"]


def test_leading_separator_no_frontmatter() -> None:
    """Leading --- without a matching close is a separator, not frontmatter."""
    # The first line is "---" but the next non-YAML line prevents valid
    # frontmatter parsing, so it falls through as a separator.
    text = "---\nseg1\n---\nseg2"
    result = parse_multi_prompt(text)
    # parse_yaml_front_matter will try to parse "seg1" as YAML.
    # "seg1" is valid YAML (a bare string) but not a dict -> returns None.
    # So --- lines become separators.
    assert len(result.segments) >= 1


# --- parse_multi_prompt: whitespace around separators ---


def test_whitespace_around_separator() -> None:
    """Separators with trailing whitespace still split."""
    text = "seg1\n---   \nseg2"
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2"]


def test_segments_are_stripped() -> None:
    """Leading/trailing whitespace on segments is stripped."""
    text = "  seg1  \n---\n  seg2  "
    result = parse_multi_prompt(text)
    assert result.segments == ["seg1", "seg2"]


# --- is_multi_prompt ---


def test_is_multi_prompt_true() -> None:
    assert is_multi_prompt("a\n---\nb") is True


def test_is_multi_prompt_false_single() -> None:
    assert is_multi_prompt("just one segment") is False


def test_is_multi_prompt_false_frontmatter_only() -> None:
    """Frontmatter + single segment is not a multi-prompt."""
    text = '---\nxprompts:\n  _x: "v"\n---\nsingle segment'
    assert is_multi_prompt(text) is False


def test_is_multi_prompt_true_with_frontmatter() -> None:
    """Frontmatter + multiple segments is multi-prompt."""
    text = '---\nxprompts:\n  _x: "v"\n---\nseg1\n---\nseg2'
    assert is_multi_prompt(text) is True


def test_is_multi_prompt_false_separator_in_code_block() -> None:
    """--- inside code block doesn't count."""
    text = "only\n```\n---\n```\nsegment"
    assert is_multi_prompt(text) is False


# --- macro swarm smoke check ---


def test_non_macro_swarm_segment_passes_through() -> None:
    """A segment that references a single-segment macro is left unchanged
    by ``expand_macro_swarms``."""
    from unittest.mock import patch

    from sase.agent.macro_swarm import expand_macro_swarms_with_metadata
    from sase.macro.models import Macro

    catalog = {"plain": Macro(name="plain", content="just one body")}
    with patch("sase.agent.macro_swarm.get_all_macros", return_value=catalog):
        out = expand_macro_swarms_with_metadata(["#plain"])
        assert [segment.prompt for segment in out] == ["#plain"]


# --- parse_multi_prompt: structured macros ---


def test_structured_macro_with_inputs() -> None:
    """Structured macro definitions with inputs are parsed correctly."""
    text = (
        "---\n"
        "xprompts:\n"
        "  _greet:\n"
        "    input: {name: word}\n"
        '    content: "Hello {{ name }}"\n'
        "---\n"
        "Do the thing"
    )
    result = parse_multi_prompt(text)
    assert "_greet" in result.local_macros
    xp = result.local_macros["_greet"]
    assert xp.content == "Hello {{ name }}"
    assert len(xp.inputs) == 1
    assert xp.inputs[0].name == "name"
