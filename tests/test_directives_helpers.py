"""Tests for directive helper functions (has_wait, has_model, split_prompt, _parse_duration, _parse_absolute_time)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    _parse_absolute_time,
    has_model_directive,
    has_wait_directive,
    split_prompt_for_models,
    _parse_duration,
)


# --- has_wait_directive tests ---


def test_has_wait_directive_colon() -> None:
    """Detects %wait:name syntax."""
    assert has_wait_directive("Do something %wait:faster") is True


def test_has_wait_directive_alias() -> None:
    """Detects %w:name shorthand."""
    assert has_wait_directive("Do something %w:faster") is True


def test_has_wait_directive_paren() -> None:
    """Detects %wait(name) syntax."""
    assert has_wait_directive("Do something %wait(faster)") is True


def test_has_wait_directive_plus() -> None:
    """Detects %wait+ and %w+ syntax."""
    assert has_wait_directive("Do something %wait+") is True
    assert has_wait_directive("Do something %w+") is True


def test_has_wait_directive_start_of_line() -> None:
    """Detects %wait at start of line."""
    assert has_wait_directive("%wait:faster\nDo something") is True


def test_has_wait_directive_absent() -> None:
    """Returns False when no %wait directive present."""
    assert has_wait_directive("Do something %model:opus") is False


def test_has_wait_directive_bare() -> None:
    """Detects bare %wait (no argument)."""
    assert has_wait_directive("%wait\nDo something") is True
    assert has_wait_directive("Do something %wait") is True
    assert has_wait_directive("Do something %w\nmore") is True


def test_has_wait_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_wait_directive("Just a plain prompt") is False


def test_has_wait_directive_duration() -> None:
    """has_wait_directive detects %wait:5m."""
    assert has_wait_directive("%wait:5m\nDo something") is True


# --- has_model_directive tests ---


def test_has_model_directive_colon() -> None:
    """Detects %model:name syntax."""
    assert has_model_directive("%model:opus\nDo something") is True


def test_has_model_directive_alias_colon() -> None:
    """Detects %m:name shorthand."""
    assert has_model_directive("Do something %m:sonnet") is True


def test_has_model_directive_paren() -> None:
    """Detects %m(name) syntax."""
    assert has_model_directive("Do something %m(opus)") is True


def test_has_model_directive_absent() -> None:
    """Returns False when no %model directive present."""
    assert has_model_directive("Do something %wait:faster") is False


def test_has_model_directive_no_percent() -> None:
    """Returns False quickly when no % in prompt."""
    assert has_model_directive("Just a plain prompt") is False


# --- split_prompt_for_models tests ---


def test_split_prompt_for_models_two_models() -> None:
    """Two models produce two prompts, each with a single %model directive."""
    prompt = "%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:opus\nReview this code"
    assert result[1] == "%model:sonnet\nReview this code"


def test_split_prompt_for_models_three_models() -> None:
    """Three models produce three prompts."""
    prompt = "%model(opus,sonnet,haiku)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%model:opus\nDo work"
    assert result[1] == "%model:sonnet\nDo work"
    assert result[2] == "%model:haiku\nDo work"


def test_split_prompt_for_models_single_model_returns_none() -> None:
    """Single model in parens returns None (not multi-model)."""
    assert split_prompt_for_models("%m(opus)\nDo work") is None


def test_split_prompt_for_models_no_directive_returns_none() -> None:
    """No model directive returns None."""
    assert split_prompt_for_models("Just a prompt") is None


def test_split_prompt_for_models_colon_syntax_returns_none() -> None:
    """Colon syntax is single model, returns None."""
    assert split_prompt_for_models("%m:opus\nDo work") is None


def test_split_prompt_for_models_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%approve\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%approve\n%model:opus\nReview this code"
    assert result[1] == "%approve\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%m(codex/o3,claude/opus)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:codex/o3\nReview this code"
    assert result[1] == "%model:claude/opus\nReview this code"


def test_split_prompt_for_models_spaces_in_args() -> None:
    """Spaces around model names in args are handled."""
    prompt = "%m(opus, sonnet)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%model:opus\nDo work"
    assert result[1] == "%model:sonnet\nDo work"


def test_split_prompt_for_models_after_xprompt_expansion() -> None:
    """Xprompt-expanded %m(...) is correctly split by split_prompt_for_models."""
    from sase.xprompt.processor import process_xprompt_references

    # Simulate what happens when #swarm expands to %m(opus,sonnet)
    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        wraps=process_xprompt_references,
    ):
        expanded = "%m(opus,sonnet)\nReview this code"
        result = split_prompt_for_models(expanded)
        assert result is not None
        assert len(result) == 2
        assert result[0] == "%model:opus\nReview this code"
        assert result[1] == "%model:sonnet\nReview this code"


# --- _parse_duration tests ---


def test__parse_duration_minutes() -> None:
    """'5m' parses to 300 seconds."""
    assert _parse_duration("5m") == 300.0


def test__parse_duration_hours() -> None:
    """'1h' parses to 3600 seconds."""
    assert _parse_duration("1h") == 3600.0


def test__parse_duration_seconds() -> None:
    """'90s' parses to 90 seconds."""
    assert _parse_duration("90s") == 90.0


def test__parse_duration_hours_minutes() -> None:
    """'2h30m' parses to 9000 seconds."""
    assert _parse_duration("2h30m") == 9000.0


def test__parse_duration_full() -> None:
    """'1h30m15s' parses to 5415 seconds."""
    assert _parse_duration("1h30m15s") == 5415.0


def test__parse_duration_zero() -> None:
    """'0s' parses to 0."""
    assert _parse_duration("0s") == 0.0


def test__parse_duration_all_zeros() -> None:
    """'0h0m0s' parses to 0."""
    assert _parse_duration("0h0m0s") == 0.0


def test__parse_duration_invalid_unit() -> None:
    """'5x' is not a valid duration."""
    assert _parse_duration("5x") is None


def test__parse_duration_wrong_order() -> None:
    """'5m3h' is not valid (units must be h > m > s)."""
    assert _parse_duration("5m3h") is None


def test__parse_duration_duplicate_unit() -> None:
    """'5m5m' is not valid."""
    assert _parse_duration("5m5m") is None


def test__parse_duration_agent_name() -> None:
    """Agent names (start with letter) return None."""
    assert _parse_duration("abc") is None


def test__parse_duration_empty() -> None:
    """Empty string returns None."""
    assert _parse_duration("") is None


# --- _parse_absolute_time tests ---


def test__parse_absolute_time_hhmm_future() -> None:
    """HHMM in the future returns today's ISO string."""
    # Use 23:59 which is almost certainly in the future relative to test time
    # (unless tests run at exactly 23:59)
    tomorrow = datetime.now() + timedelta(days=1)
    result = _parse_absolute_time(tomorrow.strftime("%H%M"))
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.hour == tomorrow.hour
    assert target.minute == tomorrow.minute


def test__parse_absolute_time_hhmm_past_wraps_to_tomorrow() -> None:
    """HHMM in the past wraps to tomorrow."""
    # Use 00:00 which is almost certainly in the past
    result = _parse_absolute_time("0000")
    assert result is not None
    target = datetime.fromisoformat(result)
    # Should be tomorrow (since 00:00 today has passed)
    assert target.date() == (datetime.now() + timedelta(days=1)).date()


def test__parse_absolute_time_yymmdd_hhmm_future() -> None:
    """yymmdd/HHMM in the future returns correct ISO string."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    result = _parse_absolute_time(f"{date_str}/1430")
    assert result is not None
    target = datetime.fromisoformat(result)
    assert target.year == future.year
    assert target.month == future.month
    assert target.day == future.day
    assert target.hour == 14
    assert target.minute == 30


def test__parse_absolute_time_yymmdd_hhmm_past_raises() -> None:
    """yymmdd/HHMM in the past raises DirectiveError."""
    past = datetime.now() - timedelta(days=30)
    date_str = past.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="in the past"):
        _parse_absolute_time(f"{date_str}/0000")


def test__parse_absolute_time_invalid_hour() -> None:
    """Hour > 23 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        _parse_absolute_time("2500")


def test__parse_absolute_time_invalid_minute() -> None:
    """Minute > 59 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="minutes 00-59"):
        _parse_absolute_time("1261")


def test__parse_absolute_time_invalid_month() -> None:
    """Month > 12 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="month must be 01-12"):
        _parse_absolute_time("261311/1430")


def test__parse_absolute_time_invalid_day() -> None:
    """Day > 31 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="day must be 01-31"):
        _parse_absolute_time("260132/1430")


def test__parse_absolute_time_invalid_date_combo() -> None:
    """Feb 30 raises DirectiveError."""
    with pytest.raises(DirectiveError, match="Invalid date/time"):
        _parse_absolute_time("260230/1430")


def test__parse_absolute_time_no_match() -> None:
    """Non-matching strings return None."""
    assert _parse_absolute_time("abc") is None
    assert _parse_absolute_time("5m") is None
    assert _parse_absolute_time("12345") is None
    assert _parse_absolute_time("") is None


def test__parse_absolute_time_yymmdd_invalid_hour() -> None:
    """yymmdd/HHMM with invalid hour raises DirectiveError."""
    future = datetime.now() + timedelta(days=30)
    date_str = future.strftime("%y%m%d")
    with pytest.raises(DirectiveError, match="hours must be 00-23"):
        _parse_absolute_time(f"{date_str}/2500")
