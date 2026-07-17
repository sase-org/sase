"""Tests for the shared compact agent status-count chip."""

from rich.text import Text

from sase.ace.tui.agent_count_chip import (
    AGENT_COUNT_CHIP_METRIC_STYLES,
    AGENT_COUNT_CHIP_NEUTRAL_STYLE,
    format_agent_count_chip,
)


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def test_agent_count_chip_is_empty_when_all_counts_are_zero() -> None:
    chip = format_agent_count_chip()

    assert chip.plain == ""
    assert chip.spans == []


def test_agent_count_chip_renders_one_status_and_multi_digit_count() -> None:
    chip = format_agent_count_chip(running=12)

    assert chip.plain == "[R12]"
    assert _style_at(chip, 0) == AGENT_COUNT_CHIP_NEUTRAL_STYLE
    assert _style_at(chip, 1) == AGENT_COUNT_CHIP_NEUTRAL_STYLE
    assert _style_at(chip, 2) == AGENT_COUNT_CHIP_METRIC_STYLES["running"]
    assert _style_at(chip, 3) == AGENT_COUNT_CHIP_METRIC_STYLES["running"]
    assert _style_at(chip, 4) == AGENT_COUNT_CHIP_NEUTRAL_STYLE


def test_agent_count_chip_uses_canonical_order_and_status_styles() -> None:
    chip = format_agent_count_chip(
        stopped=1,
        running=2,
        waiting=3,
        failed=4,
        unread=5,
        done=6,
    )

    assert chip.plain == "[S1 R2 W3 F4 U5 D6]"
    for token, metric in (
        ("S1", "stopped"),
        ("R2", "running"),
        ("W3", "waiting"),
        ("F4", "failed"),
        ("D6", "done"),
    ):
        letter = chip.plain.index(token)
        assert _style_at(chip, letter) == AGENT_COUNT_CHIP_NEUTRAL_STYLE
        assert _style_at(chip, letter + 1) == AGENT_COUNT_CHIP_METRIC_STYLES[metric]

    unread = chip.plain.index("U5")
    assert _style_at(chip, unread) == AGENT_COUNT_CHIP_METRIC_STYLES["unread"]
    assert _style_at(chip, unread + 1) == AGENT_COUNT_CHIP_METRIC_STYLES["unread"]

    for position, character in enumerate(chip.plain):
        if character in "[] ":
            assert _style_at(chip, position) == AGENT_COUNT_CHIP_NEUTRAL_STYLE


def test_agent_count_chip_suppresses_zero_metrics() -> None:
    chip = format_agent_count_chip(stopped=0, waiting=7, unread=0, done=8)

    assert chip.plain == "[W7 D8]"
