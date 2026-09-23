"""Tests for the StashedPromptsIndicator widget rendering."""

from sase.ace.tui.widgets.stashed_prompts_indicator import (
    StashedPromptsIndicator,
)


def test_zero_count_renders_empty_hidden_badge() -> None:
    text = StashedPromptsIndicator._build_content(0)
    assert text.plain == ""


def test_positive_count_renders_pink_stack_badge() -> None:
    text = StashedPromptsIndicator._build_content(4)
    assert text.plain == " ≡ 4 "
    assert text.style == "bold #1a1a1a on #FF87D7"


def test_negative_count_is_treated_as_empty() -> None:
    # Defensive: a negative count should never paint a badge.
    text = StashedPromptsIndicator._build_content(-2)
    assert text.plain == ""


def test_tooltip_describes_stash_size() -> None:
    assert StashedPromptsIndicator._build_tooltip(0) == (
        "No stashed prompts\nClick to open the prompt stash"
    )
    assert StashedPromptsIndicator._build_tooltip(1) == (
        "1 stashed prompt\nClick to open the prompt stash"
    )
    assert StashedPromptsIndicator._build_tooltip(4) == (
        "4 stashed prompts\nClick to open the prompt stash"
    )


def test_set_count_updates_state_and_tooltip() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(2)
    assert indicator._count == 2
    assert indicator.pinned_count == 0
    assert indicator.tooltip == "2 stashed prompts\nClick to open the prompt stash"


def test_set_count_clamps_negative_to_zero() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(-5)
    assert indicator._count == 0
    assert indicator.pinned_count == 0
    assert indicator.tooltip == "No stashed prompts\nClick to open the prompt stash"


def test_set_count_tracks_pinned_count_without_changing_badge_text() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(3, pinned_count=2)
    assert indicator.count == 3
    assert indicator.pinned_count == 2
    assert StashedPromptsIndicator._build_content(indicator.count).plain == " ≡ 3 "


def test_set_count_clamps_pinned_count_to_total() -> None:
    indicator = StashedPromptsIndicator()
    indicator.set_count(1, pinned_count=4)
    assert indicator.count == 1
    assert indicator.pinned_count == 1
