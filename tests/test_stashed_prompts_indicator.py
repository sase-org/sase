"""Tests for the StashedPromptsIndicator widget rendering."""

from sase.ace.tui.widgets.stashed_prompts_indicator import (
    StashedPromptsIndicator,
)


def test_zero_count_renders_empty_hidden_badge() -> None:
    text = StashedPromptsIndicator._build_content(0)
    assert text.plain == ""


def test_positive_count_renders_violet_snowflake_badge() -> None:
    text = StashedPromptsIndicator._build_content(3)
    assert text.plain == " ❄ 3 "
    assert "#AF87FF" in str(text.style)


def test_negative_count_is_treated_as_empty() -> None:
    # Defensive: a negative count should never paint a badge.
    text = StashedPromptsIndicator._build_content(-2)
    assert text.plain == ""


def test_tooltip_describes_stash_size() -> None:
    assert StashedPromptsIndicator._build_tooltip(0) == "No stashed prompts"
    assert StashedPromptsIndicator._build_tooltip(1) == "1 stashed prompt"
    assert StashedPromptsIndicator._build_tooltip(4) == "4 stashed prompts"


def test_set_count_updates_state_and_tooltip() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(2)
    assert indicator._count == 2
    assert indicator.tooltip == "2 stashed prompts"


def test_set_count_clamps_negative_to_zero() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(-5)
    assert indicator._count == 0
    assert indicator.tooltip == "No stashed prompts"
