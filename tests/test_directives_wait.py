"""Tests for wait prompt directives."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_wait_directive_multiple() -> None:
    """Two %wait lines yield wait=['a', 'b']."""
    prompt = "%wait:a\n%wait:b\nDo some work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do some work"
    assert directives.wait == ["a", "b"]


def test_wait_bare_resolves_to_previous_agent() -> None:
    """Bare %wait resolves to the most recently named previous agent."""
    prompt = "%name:foo\n%wait\nDo work"
    with patch(
        "sase.agent.names.get_most_recent_agent_name",
        return_value="prev",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.wait == ["prev"]


def test_wait_bare_with_bare_name_does_not_self_wait() -> None:
    """Bare %wait + bare %name does NOT wait for itself."""
    prompt = "%name\n%wait\nDo work"
    with (
        patch(
            "sase.agent.names.get_next_auto_name",
            return_value="b",
        ),
        patch(
            "sase.agent.names.get_most_recent_agent_name",
            return_value="a",
        ),
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"
    assert directives.wait == ["a"]


def test_wait_bare_no_previous_agent_raises() -> None:
    """Bare %wait with no previously named agent raises DirectiveError."""
    prompt = "%wait\nDo work"
    with patch(
        "sase.agent.names.get_most_recent_agent_name",
        return_value=None,
    ):
        with pytest.raises(DirectiveError, match="no previously.*named agent"):
            extract_prompt_directives(prompt)


def test_wait_mixed_bare_and_explicit() -> None:
    """Mix of bare and explicit %wait works."""
    prompt = "%name:foo\n%wait:bar\n%wait\nDo work"
    with patch(
        "sase.agent.names.get_most_recent_agent_name",
        return_value="prev",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["bar", "prev"]


def test_wait_template_resolves_latest() -> None:
    """%w:foo-@ resolves to the highest existing concrete template name."""
    prompt = "%w:foo-@\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        return_value={"foo-1", "foo-4", "foo-a", "bar-99"},
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["foo-a"]


def test_wait_template_comma_args() -> None:
    """Comma-separated %wait templates resolve each argument independently."""
    prompt = "%wait:foo-@,@.cld\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        return_value={"foo-2", "1.cld"},
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["foo-2", "1.cld"]


def test_wait_template_middle_shape_resolves_latest() -> None:
    prompt = "%wait:research.@.final\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        return_value={"research.0.final", "research.z.final", "research.00.final"},
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["research.00.final"]


def test_wait_template_inside_fenced_block_ignored() -> None:
    prompt = "```\n%w:foo-@\n```\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        side_effect=AssertionError("fenced wait should not resolve"),
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.wait == []


def test_wait_template_no_existing_latest_raises() -> None:
    prompt = "%w:foo-@\nDo work"
    with (
        patch(
            "sase.agent.names._registry.get_reserved_agent_names",
            return_value={"foo", "foo.x"},
        ),
        pytest.raises(DirectiveError, match="No existing agent name found"),
    ):
        extract_prompt_directives(prompt)


@pytest.mark.parametrize("agent_name", ["05s", "00s", "007"])
def test_wait_leading_zero_duration_shaped_arg_is_agent_name(
    agent_name: str,
) -> None:
    """Leading-zero duration-shaped values are valid positional agent names."""
    prompt = f"%w:{agent_name}\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == [agent_name]
    assert directives.wait_duration is None
    assert directives.wait_until is None


def test_wait_time_keyword_accepts_leading_zero_duration() -> None:
    """The explicit time= path keeps lenient duration parsing."""
    prompt = "%wait(time=05s)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 5.0
    assert directives.wait_until is None


@pytest.mark.parametrize("agent_name", ["4h", "5m", "1430", "300415/0900"])
def test_wait_time_shaped_arg_is_agent_name(agent_name: str) -> None:
    """Every time-shaped positional value remains an agent dependency."""
    prompt = f"%w:{agent_name}\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == [agent_name]
    assert directives.wait_duration is None
    assert directives.wait_until is None


def test_wait_comma_two_agents() -> None:
    """%wait:a,b yields two agent-name waits."""
    prompt = "%wait:a,b\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["a", "b"]
    assert directives.wait_duration is None
    assert directives.wait_until is None


def test_wait_comma_backtick_is_single_arg() -> None:
    """%wait:`a,b` treats the comma as literal (no split)."""
    prompt = "%wait:`a,b`\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["a,b"]


def test_wait_comma_empty_segments_filtered() -> None:
    """%wait:a,,b drops empty segments, yielding ['a', 'b']."""
    prompt = "%wait:a,,b\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["a", "b"]


def test_wait_paren_form_matches_colon_form() -> None:
    """%wait(a, b) behaves the same as %wait:a,b."""
    prompt = "%wait(a, b)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["a", "b"]


def test_wait_time_keyword_sets_wait_duration() -> None:
    """%wait(time=4h) sets wait_duration and leaves wait empty."""
    prompt = "%wait(time=4h)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 14400.0
    assert directives.wait_until is None


def test_wait_time_keyword_combines_with_agent() -> None:
    """%wait(agent_a, time=5m) sets both dependency and time floor."""
    prompt = "%wait(agent_a, time=5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent_a"]
    assert directives.wait_duration == 300.0


def test_wait_runners_keyword_sets_threshold() -> None:
    cleaned, directives = extract_prompt_directives(
        "%wait(agent_a, runners=0)\nDo work"
    )

    assert cleaned == "Do work"
    assert directives.wait == ["agent_a"]
    assert directives.wait_runners == 0


@pytest.mark.parametrize("value", ["-1", "1.5", "many", ""])
def test_wait_runners_keyword_rejects_non_negative_non_integer(value: str) -> None:
    with pytest.raises(DirectiveError, match="non-negative integer"):
        extract_prompt_directives(f"%wait(runners={value})\nDo work")


def test_wait_runners_keyword_rejects_multiple_occurrences() -> None:
    prompt = "%wait(runners=1)\n%wait(runners=2)\nDo work"
    with pytest.raises(DirectiveError, match="Multiple %wait.*runners"):
        extract_prompt_directives(prompt)


def test_wait_runners_keyword_rejects_duplicate_in_one_directive() -> None:
    prompt = "%wait(runners=1, runners=2)\nDo work"
    with pytest.raises(DirectiveError, match="Duplicate keyword argument 'runners'"):
        extract_prompt_directives(prompt)


def test_wait_time_keyword_sets_wait_until() -> None:
    """%wait(time=1430) sets wait_until."""
    prompt = "%wait(time=1430)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait == []
    assert directives.wait_duration is None
    assert directives.wait_until is not None


def test_wait_time_keyword_duration_and_absolute_conflict() -> None:
    """Duration and absolute time waits cannot be combined."""
    prompt = "%wait(time=5m)\n%wait(time=1430)\nDo work"
    with pytest.raises(DirectiveError, match="Cannot combine duration and absolute"):
        extract_prompt_directives(prompt)


def test_wait_time_keyword_double_absolute_conflict() -> None:
    """Multiple absolute time waits cannot be combined."""
    prompt = "%wait(time=0000)\n%wait(time=0100)\nDo work"
    with pytest.raises(DirectiveError, match="Multiple absolute time waits"):
        extract_prompt_directives(prompt)


def test_wait_time_keyword_repeated_durations_take_max() -> None:
    """Repeated time= durations fold to the maximum."""
    prompt = "%wait(time=5m)\n%wait(time=10m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


def test_wait_unknown_keyword_raises() -> None:
    """Only the documented keywords are supported on %wait."""
    prompt = "%wait(foo=bar)\nDo work"
    with pytest.raises(DirectiveError, match=r"Unsupported keyword on %wait: foo="):
        extract_prompt_directives(prompt)
