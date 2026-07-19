"""Tests for time and repeat prompt directive types."""

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %wait time= duration directive tests ---


def test_time_duration_sets_field() -> None:
    """%wait(time=5m) sets wait_duration=300.0 and leaves wait=[]."""
    prompt = "%wait(time=5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 300.0


def test_t_aliases_tribe_not_time() -> None:
    """%t assigns a tribe without restoring the removed %time alias."""
    cleaned, directives = extract_prompt_directives("%t:review\nDo work")
    assert cleaned == "Do work"
    assert directives.tribe == "review"
    assert directives.wait_duration is None
    assert directives.auto_mode is None


def test_time_compound_duration() -> None:
    """%wait(time=1h30m) sets wait_duration=5400.0."""
    prompt = "%wait(time=1h30m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 5400.0


def test_time_seconds_duration() -> None:
    """%wait(time=90s) sets wait_duration=90.0."""
    prompt = "%wait(time=90s)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 90.0


def test_time_with_wait_agent() -> None:
    """%wait(agent, time=5m) sets both fields."""
    prompt = "%wait(agent, time=5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent"]
    assert directives.wait_duration == 300.0


def test_time_duration_multiple_takes_max() -> None:
    """Multiple time= durations take the maximum."""
    prompt = "%wait(time=5m)\n%wait(time=10m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


# --- %wait time= absolute time directive tests ---


def test_time_absolute_time_hhmm() -> None:
    """%wait(time=0000) sets wait_until to an ISO string."""
    prompt = "%wait(time=0000)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration is None
    assert directives.wait_until is not None
    assert "T00:00:00" in directives.wait_until


def test_time_absolute_time_yymmdd() -> None:
    """%wait(time=300415/0900) sets wait_until."""
    prompt = "%wait(time=300415/0900)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_until is not None
    assert directives.wait_until.startswith("2030-04-15T09:00")


def test_time_absolute_with_wait_agent() -> None:
    """Absolute time= can be combined with a wait agent."""
    prompt = "%wait(agent_a, time=0000)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["agent_a"]
    assert directives.wait_until is not None


def test_time_absolute_with_duration_raises() -> None:
    """Combining duration and absolute time waits raises DirectiveError."""
    prompt = "%wait(time=5m)\n%wait(time=0000)\nDo work"
    with pytest.raises(DirectiveError, match="Cannot combine duration and absolute"):
        extract_prompt_directives(prompt)


def test_time_absolute_multiple_raises() -> None:
    """Multiple absolute %time waits raise DirectiveError."""
    prompt = "%wait(time=0000)\n%wait(time=0100)\nDo work"
    with pytest.raises(DirectiveError, match="Multiple absolute time"):
        extract_prompt_directives(prompt)


# --- time wait error cases ---


def test_time_bare_raises() -> None:
    """Empty time= raises DirectiveError."""
    prompt = "%wait(time=)\nDo work"
    with pytest.raises(DirectiveError, match=r"%wait\(time=\.\.\.\)"):
        extract_prompt_directives(prompt)


def test_time_invalid_value_suggests_wait() -> None:
    """%wait(time=review) errors with a hint to use %wait:review."""
    prompt = "%wait(time=review)\nDo work"
    with pytest.raises(DirectiveError, match=r"%wait:review"):
        extract_prompt_directives(prompt)


# --- repeated time keyword tests ---


def test_time_comma_durations_take_max() -> None:
    """Repeated time= durations yield the maximum duration."""
    prompt = "%wait(time=5m)\n%wait(time=10m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


def test_time_paren_form() -> None:
    """%wait(time=5m) parses its named argument."""
    prompt = "%wait(time=5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait_duration == 300.0


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
    """%repeat combined with %model and %id works."""
    prompt = "%repeat:3\n%model:opus\n%id:foo\nDo the work"
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
