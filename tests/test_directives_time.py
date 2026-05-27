"""Tests for time prompt directives."""

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_time_duration_sets_field() -> None:
    """%time:5m sets wait_duration=300.0 and leaves wait=[]."""
    prompt = "%time:5m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration == 300.0


def test_time_alias_t() -> None:
    """%t:5m sets wait_duration=300.0 (alias)."""
    prompt = "%t:5m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait_duration == 300.0


def test_time_compound_duration() -> None:
    """%time:1h30m sets wait_duration=5400.0."""
    prompt = "%time:1h30m\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 5400.0


def test_time_seconds_duration() -> None:
    """%time:90s sets wait_duration=90.0."""
    prompt = "%time:90s\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 90.0


def test_time_with_wait_agent() -> None:
    """%wait:agent + %time:5m sets both fields."""
    prompt = "%wait:agent\n%time:5m\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent"]
    assert directives.wait_duration == 300.0


def test_time_duration_multiple_takes_max() -> None:
    """Multiple %time durations take the maximum."""
    prompt = "%time:5m\n%time:10m\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


def test_time_absolute_time_hhmm() -> None:
    """%time:0000 sets wait_until to an ISO string."""
    prompt = "%time:0000\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration is None
    assert directives.wait_until is not None
    assert "T00:00:00" in directives.wait_until


def test_time_absolute_time_yymmdd() -> None:
    """%time:300415/0900 sets wait_until."""
    prompt = "%time:300415/0900\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_until is not None
    assert directives.wait_until.startswith("2030-04-15T09:00")


def test_time_absolute_with_wait_agent() -> None:
    """Absolute %time can be combined with %wait:agent."""
    prompt = "%wait:agent_a\n%time:0000\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["agent_a"]
    assert directives.wait_until is not None


def test_time_absolute_with_duration_raises() -> None:
    """Combining %time:5m and %time:0000 raises DirectiveError."""
    prompt = "%time:5m\n%time:0000\nDo work"
    with pytest.raises(DirectiveError, match="Cannot combine duration and absolute"):
        extract_prompt_directives(prompt)


def test_time_absolute_multiple_raises() -> None:
    """Multiple absolute %time waits raise DirectiveError."""
    prompt = "%time:0000\n%time:0100\nDo work"
    with pytest.raises(DirectiveError, match="Multiple absolute time"):
        extract_prompt_directives(prompt)


def test_time_bare_raises() -> None:
    """Bare %time raises DirectiveError."""
    prompt = "%time\nDo work"
    with pytest.raises(DirectiveError, match="Bare '%time' requires"):
        extract_prompt_directives(prompt)


def test_time_invalid_value_suggests_wait() -> None:
    """%time:review errors with a hint to use %wait:review."""
    prompt = "%time:review\nDo work"
    with pytest.raises(DirectiveError, match=r"%wait:review"):
        extract_prompt_directives(prompt)


def test_time_comma_durations_take_max() -> None:
    """%time:5m,10m yields the maximum duration."""
    prompt = "%time:5m,10m\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


def test_time_paren_form() -> None:
    """%time(5m) behaves the same as %time:5m."""
    prompt = "%time(5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait_duration == 300.0
