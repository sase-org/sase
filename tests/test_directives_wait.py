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


def test_wait_duration_arg_raises_with_migration_hint() -> None:
    """%wait:5m raises with a migration hint pointing to %time."""
    prompt = "%wait:5m\nDo work"
    with pytest.raises(DirectiveError, match=r"%time:5m"):
        extract_prompt_directives(prompt)


def test_wait_hhmm_arg_raises_with_migration_hint() -> None:
    """%wait:1430 raises with a migration hint pointing to %time."""
    prompt = "%wait:1430\nDo work"
    with pytest.raises(DirectiveError, match=r"%time:1430"):
        extract_prompt_directives(prompt)


def test_wait_yymmdd_arg_raises_with_migration_hint() -> None:
    """%wait:300415/0900 raises with a migration hint pointing to %time."""
    prompt = "%wait:300415/0900\nDo work"
    with pytest.raises(DirectiveError, match=r"%time:300415/0900"):
        extract_prompt_directives(prompt)


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
