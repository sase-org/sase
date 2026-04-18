"""Tests for individual directive types (%approve, %name, %wait, %plan, %hide, %edit, %repeat)."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %approve directive tests ---


def test_approve_bare() -> None:
    """%approve (bare) sets approve=True."""
    prompt = "%approve\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_plus() -> None:
    """%approve+ sets approve=True."""
    prompt = "%approve+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_alias() -> None:
    """%a (alias) sets approve=True."""
    prompt = "%a\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_default_false() -> None:
    """Default approve is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.approve is False


def test_approve_with_other_directives() -> None:
    """%approve combined with %model works."""
    prompt = "%approve\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True
    assert directives.model == "opus"


def test_approve_duplicate_raises() -> None:
    """Duplicate %approve raises DirectiveError."""
    prompt = "%approve\n%approve\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%approve'"):
        extract_prompt_directives(prompt)


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


# --- %wait duration directive tests ---


def test_wait_duration_sets_field() -> None:
    """%wait:5m sets wait_duration=300.0 and wait=[]."""
    prompt = "%wait:5m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 300.0


def test_wait_duration_and_agent_name() -> None:
    """Mixed %wait:agent and %wait:5m sets both fields."""
    prompt = "%wait:agent\n%wait:5m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent"]
    assert directives.wait_duration == 300.0


def test_wait_duration_multiple_takes_max() -> None:
    """Multiple duration waits take the maximum."""
    prompt = "%wait:5m\n%wait:10m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 600.0


# --- %wait absolute time directive tests ---


def test_wait_absolute_time_hhmm() -> None:
    """%wait:1430 sets wait_until to an ISO string."""
    prompt = "%wait:0000\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration is None
    assert directives.wait_until is not None
    assert "T00:00:00" in directives.wait_until


def test_wait_absolute_time_with_agent_names() -> None:
    """Absolute time can be combined with agent-name waits."""
    prompt = "%wait:agent_a\n%wait:0000\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent_a"]
    assert directives.wait_until is not None


def test_wait_absolute_time_with_duration_raises() -> None:
    """Combining absolute time and duration raises DirectiveError."""
    prompt = "%wait:5m\n%wait:0000\nDo work"
    with pytest.raises(DirectiveError, match="Cannot combine duration and absolute"):
        extract_prompt_directives(prompt)


def test_wait_absolute_time_multiple_raises() -> None:
    """Multiple absolute time waits raise DirectiveError."""
    prompt = "%wait:0000\n%wait:0100\nDo work"
    with pytest.raises(DirectiveError, match="Multiple absolute time"):
        extract_prompt_directives(prompt)


# --- %plan directive tests ---


def test_plan_bare() -> None:
    """%plan (bare) sets plan=True."""
    prompt = "%plan\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_plus() -> None:
    """%plan+ sets plan=True."""
    prompt = "%plan+\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_alias() -> None:
    """%p (alias) sets plan=True."""
    prompt = "%p\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True


def test_plan_default_false() -> None:
    """Default plan is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.plan is False


def test_plan_with_approve() -> None:
    """%plan combined with %approve both work together."""
    prompt = "%plan\n%approve\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Fix the bug"
    assert directives.plan is True
    assert directives.approve is True


def test_plan_duplicate_raises() -> None:
    """Duplicate %plan raises DirectiveError."""
    prompt = "%plan\n%plan\nFix the bug"
    with pytest.raises(DirectiveError, match="Duplicate directive '%plan'"):
        extract_prompt_directives(prompt)


# --- %hide directive tests ---


def test_hide_bare() -> None:
    """%hide (bare) sets hide=True."""
    prompt = "%hide\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_plus() -> None:
    """%hide+ sets hide=True."""
    prompt = "%hide+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_alias() -> None:
    """%h (alias) sets hide=True."""
    prompt = "%h\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_default_false() -> None:
    """Default hide is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.hide is False


def test_hide_with_other_directives() -> None:
    """%hide combined with %model works."""
    prompt = "%hide\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True
    assert directives.model == "opus"


def test_hide_duplicate_raises() -> None:
    """Duplicate %hide raises DirectiveError."""
    prompt = "%hide\n%hide\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%hide'"):
        extract_prompt_directives(prompt)


# --- %edit directive tests ---


def test_edit_bare() -> None:
    """%edit (bare) sets edit=True."""
    prompt = "%edit\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.edit is True


def test_edit_alias() -> None:
    """%e (alias) sets edit=True."""
    prompt = "%e\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.edit is True


def test_edit_inside_fenced_block_ignored() -> None:
    """%edit inside triple backticks is not extracted."""
    prompt = "```\n%edit\n```"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.edit is False


def test_edit_duplicate_raises() -> None:
    """Duplicate %edit raises DirectiveError."""
    prompt = "%edit\n%edit\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%edit'"):
        extract_prompt_directives(prompt)


# --- %repeat directive tests ---


def test_repeat_colon_arg() -> None:
    """%repeat:3 sets repeat_count=3."""
    prompt = "%repeat:3\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 3


def test_repeat_alias_r() -> None:
    """%r:5 (short alias) sets repeat_count=5."""
    prompt = "%r:5\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 5


def test_repeat_paren_arg() -> None:
    """%repeat(10) sets repeat_count=10."""
    prompt = "%repeat(10)\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 10


def test_repeat_bare_raises() -> None:
    """Bare %repeat without argument raises DirectiveError."""
    prompt = "%repeat\nDo the work"
    with pytest.raises(DirectiveError, match="requires a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_zero_raises() -> None:
    """%repeat:0 raises DirectiveError."""
    prompt = "%repeat:0\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_negative_raises() -> None:
    """%repeat:-1 raises DirectiveError."""
    prompt = "%repeat:-1\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_non_integer_raises() -> None:
    """%repeat:abc raises DirectiveError."""
    prompt = "%repeat:abc\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_one_is_valid() -> None:
    """%repeat:1 is valid (no-op, but allowed)."""
    prompt = "%repeat:1\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 1


def test_repeat_with_other_directives() -> None:
    """%repeat combined with %model and %name works."""
    prompt = "%repeat:3\n%model:opus\n%name:foo\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 3
    assert directives.model == "opus"
    assert directives.name == "foo"


def test_repeat_duplicate_raises() -> None:
    """Duplicate %repeat raises DirectiveError."""
    prompt = "%repeat:3\n%repeat:5\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%repeat'"):
        extract_prompt_directives(prompt)


def test_repeat_default_none() -> None:
    """Default repeat_count is None."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.repeat_count is None


def test_extract_prompt_directives_preserves_repeat_for_launcher() -> None:
    """Sanity check that the directive parser stays in sync with the launcher."""
    from sase.agent.repeat_launcher import extract_repeat_and_name

    prompt = "%r:4 do X"
    _, directives = extract_prompt_directives(prompt)
    assert directives.repeat_count == 4

    launcher_count, launcher_base, _ = extract_repeat_and_name(prompt)
    assert launcher_count == directives.repeat_count
    assert launcher_base is None
