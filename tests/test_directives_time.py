"""Tests for time prompt directives."""

import pytest

from sase.llm_provider.preprocessing import preprocess_prompt_early
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_wait_time_duration_sets_field() -> None:
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
    assert directives.wait_until is None
    assert directives.auto_mode is None


def test_wait_time_compound_duration() -> None:
    """%wait(time=1h30m) sets wait_duration=5400.0."""
    prompt = "%wait(time=1h30m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 5400.0


def test_wait_time_seconds_duration() -> None:
    """%wait(time=90s) sets wait_duration=90.0."""
    prompt = "%wait(time=90s)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 90.0


def test_wait_time_with_wait_agent() -> None:
    """%wait(agent, time=5m) sets both wait and wait_duration."""
    prompt = "%wait(agent, time=5m)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == ["agent"]
    assert directives.wait_duration == 300.0


def test_wait_time_duration_multiple_takes_max() -> None:
    """Multiple time= durations take the maximum."""
    prompt = "%wait(time=5m)\n%wait(time=10m)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_duration == 600.0


def test_wait_time_absolute_time_hhmm() -> None:
    """%wait(time=0000) sets wait_until to an ISO string."""
    prompt = "%wait(time=0000)\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.wait == []
    assert directives.wait_duration is None
    assert directives.wait_until is not None
    assert "T00:00:00" in directives.wait_until


def test_wait_time_absolute_time_yymmdd() -> None:
    """%wait(time=300415/0900) sets wait_until."""
    prompt = "%wait(time=300415/0900)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait_until is not None
    assert directives.wait_until.startswith("2030-04-15T09:00")


def test_wait_time_absolute_with_wait_agent() -> None:
    """Absolute time= can be combined with a wait agent."""
    prompt = "%wait(agent_a, time=0000)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.wait == ["agent_a"]
    assert directives.wait_until is not None


def test_wait_time_absolute_with_duration_raises() -> None:
    """Combining duration and absolute time waits raises DirectiveError."""
    prompt = "%wait(time=5m)\n%wait(time=0000)\nDo work"
    with pytest.raises(DirectiveError, match="Cannot combine duration and absolute"):
        extract_prompt_directives(prompt)


def test_wait_time_absolute_multiple_raises() -> None:
    """Multiple absolute time waits raise DirectiveError."""
    prompt = "%wait(time=0000)\n%wait(time=0100)\nDo work"
    with pytest.raises(DirectiveError, match="Multiple absolute time"):
        extract_prompt_directives(prompt)


def test_wait_time_empty_raises() -> None:
    """Empty time= raises DirectiveError."""
    prompt = "%wait(time=)\nDo work"
    with pytest.raises(DirectiveError, match=r"%wait\(time=\.\.\.\)"):
        extract_prompt_directives(prompt)


def test_time_directive_raises_migration_hint() -> None:
    """%time raises with a migration hint."""
    prompt = "%time:5m\nDo work"
    with pytest.raises(DirectiveError, match=r"#t:<time>.*%wait\(time=<time>\)"):
        extract_prompt_directives(prompt)


def test_wait_time_invalid_value_suggests_positional_wait() -> None:
    """Invalid time= values point agent waits back to positional %wait."""
    prompt = "%wait(time=review)\nDo work"
    with pytest.raises(DirectiveError, match=r"%wait:review"):
        extract_prompt_directives(prompt)


def test_wait_time_xprompt_colon_form() -> None:
    """#t:4h expands through preprocessing to wait_duration."""
    result = preprocess_prompt_early("#t:4h\nDo work")
    assert result.prompt.strip() == "Do work"
    assert result.directives.wait == []
    assert result.directives.wait_duration == 14400.0


def test_wait_time_xprompt_paren_form() -> None:
    """#t(5m) expands through preprocessing to wait_duration."""
    result = preprocess_prompt_early("#t(5m)\nDo work")
    assert result.prompt.strip() == "Do work"
    assert result.directives.wait_duration == 300.0


def test_wait_time_xprompt_named_absolute_time() -> None:
    """#t(time=300415/0900) expands through preprocessing to wait_until."""
    result = preprocess_prompt_early("#t(time=300415/0900)\nDo work")
    assert result.prompt.strip() == "Do work"
    assert result.directives.wait_until is not None
    assert result.directives.wait_until.startswith("2030-04-15T09:00")
