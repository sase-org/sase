"""Tests for naming and wait prompt directive types."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %name directive tests ---


def test_name_bare_auto_generates() -> None:
    """Bare %name auto-generates a name via get_next_auto_name()."""
    prompt = "%name\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "a"


def test_name_bare_alias_auto_generates() -> None:
    """Bare %n auto-generates a name."""
    prompt = "%n\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="b",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"


def test_name_bare_is_not_explicit() -> None:
    """Bare %name (auto-named) leaves name_explicit=False."""
    prompt = "%name\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.name_explicit is False


def test_no_name_directive_is_not_explicit() -> None:
    """No %name directive leaves name_explicit=False."""
    _, directives = extract_prompt_directives("Do work")
    assert directives.name_explicit is False


def test_name_with_arg_is_explicit() -> None:
    """%name:foo sets name_explicit=True."""
    prompt = "%name:foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is False


def test_name_force_reuse_arg_sets_separate_flag() -> None:
    """%name:!foo keeps the actual name separate from forced reuse intent."""
    prompt = "%name:!foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is True


def test_name_paren_arg_is_explicit() -> None:
    """%name(foo) sets name_explicit=True."""
    prompt = "%name(foo)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_backtick_arg_is_explicit() -> None:
    """%name:`foo` sets name_explicit=True."""
    prompt = "%name:`foo`\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_template_colon_arg() -> None:
    """%n:foo-@ is parsed as one template argument."""
    prompt = "%n:foo-@\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "foo-@"
    assert directives.name_explicit is True
    assert directives.name_template == "foo-@"
    assert directives.name_template_base == "foo"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_template_paren_arg() -> None:
    """%name(foo-@) is parsed as a template argument."""
    _, directives = extract_prompt_directives("%name(foo-@)\nDo work")
    assert directives.name == "foo-@"
    assert directives.name_template == "foo-@"
    assert directives.name_template_base == "foo"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_template_rejects_force_reuse() -> None:
    prompt = "%name:!foo-@\nDo work"
    with pytest.raises(DirectiveError, match="forced name reuse"):
        extract_prompt_directives(prompt)


def test_name_template_bare_marker_arg() -> None:
    _, directives = extract_prompt_directives("%name:@\nDo work")
    assert directives.name == "@"
    assert directives.name_template == "@"
    assert directives.name_template_base == "@"
    assert directives.name_indexed_template is True


def test_name_template_suffix_shape_arg() -> None:
    _, directives = extract_prompt_directives("%name:@.cld\nDo work")
    assert directives.name == "@.cld"
    assert directives.name_template == "@.cld"
    assert directives.name_template_base == "cld"
    assert directives.name_indexed_template is True


def test_name_template_middle_shape_arg() -> None:
    _, directives = extract_prompt_directives("%name:research.@.final\nDo work")
    assert directives.name == "research.@.final"
    assert directives.name_template == "research.@.final"
    assert directives.name_template_base == "research.final"
    assert directives.name_indexed_template is True


# --- %wait directive tests ---


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
    prompt = "%wait:foo-@,cld-@\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        return_value={"foo-2", "cld-1"},
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["foo-2", "cld-1"]


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


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("%wait:@epic\nDo work", "@epic"),
        ("%w:`@review`\nDo work", "@review"),
        ("%wait(@builders)\nDo work", "@builders"),
    ],
)
def test_wait_tribe_reference_round_trips_verbatim(
    prompt: str,
    expected: str,
) -> None:
    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Do work"
    assert directives.wait == [expected]


def test_wait_tribe_reference_mixed_with_agent_and_template() -> None:
    prompt = "%wait(@epic, builder-2, base-@)\nDo work"
    with patch(
        "sase.agent.names._registry.get_reserved_agent_names",
        return_value={"base-3"},
    ):
        cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Do work"
    assert directives.wait == ["@epic", "builder-2", "base-3"]


@pytest.mark.parametrize(
    "prompt",
    [
        "%wait:@\nDo work",
        "%wait:`@bad name`\nDo work",
        '%wait("@bad/name")\nDo work',
    ],
)
def test_wait_tribe_reference_rejects_malformed_name(prompt: str) -> None:
    with pytest.raises(DirectiveError, match="Invalid '%wait' tribe reference"):
        extract_prompt_directives(prompt)


def test_wait_tribe_reference_does_not_collide_with_tribe_directive() -> None:
    cleaned, directives = extract_prompt_directives("%t:epic\n%w:@epic\nDo work")

    assert cleaned == "Do work"
    assert directives.tag == "epic"
    assert directives.wait == ["@epic"]


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


# --- %wait time-shaped agent-name tests ---


@pytest.mark.parametrize("agent_name", ["4h", "5m", "1430", "300415/0900"])
def test_wait_time_shaped_arg_is_agent_name(agent_name: str) -> None:
    """Every time-shaped positional value remains an agent dependency."""
    prompt = f"%w:{agent_name}\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == [agent_name]
    assert directives.wait_duration is None
    assert directives.wait_until is None


# --- %wait comma-separated colon-arg tests ---


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


def test_model_colon_arg_with_comma_is_single_value() -> None:
    """Single-value %model:a,b keeps the whole string and leaves no stray text."""
    prompt = "%model:a,b\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.model == "a,b"
