"""Tests for the startup stopwatch in KeybindingFooter."""

from __future__ import annotations

from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter


def test_default_state_shows_stopwatch() -> None:
    """A freshly instantiated footer renders the gold stopwatch badge."""
    footer = KeybindingFooter()
    assert footer._startup_stopwatch_active is True
    text = footer._get_status_text()
    assert "⏱" in text.plain
    assert "starting" in text.plain
    # Leading spaces before the timer glyph match the padded-badge convention.
    assert text.plain.startswith("  ⏱ starting")


def test_elapsed_formatting_one_decimal() -> None:
    """Elapsed time is rendered with one decimal place (rounded)."""
    footer = KeybindingFooter()
    footer._startup_elapsed = 2.4
    assert "2.4s" in footer._get_status_text().plain

    footer._startup_elapsed = 12.75
    assert "12.8s" in footer._get_status_text().plain

    footer._startup_elapsed = 0.1
    assert "0.1s" in footer._get_status_text().plain


def test_slow_threshold_shifts_color() -> None:
    """Past the slow threshold the badge uses dark-orange instead of gold."""
    footer = KeybindingFooter()
    footer._startup_elapsed = 1.0
    gold_spans = footer._get_status_text().spans
    assert any("rgb(255,215,0)" in str(span.style) for span in gold_spans)

    footer._startup_elapsed = 15.0
    orange_spans = footer._get_status_text().spans
    assert any("rgb(255,140,0)" in str(span.style) for span in orange_spans)


def test_end_transitions_to_real_status() -> None:
    """After end_startup_stopwatch(), the real AXE pill appears."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    assert footer._startup_stopwatch_active is False

    stopped = footer._get_status_text().plain
    assert "⏱" not in stopped
    assert "STOPPED" in stopped

    footer._axe_running = True
    running = footer._get_status_text().plain
    assert "⏱" not in running
    assert "RUNNING" in running


def test_end_is_idempotent() -> None:
    """Calling end_startup_stopwatch() twice is safe."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    footer.end_startup_stopwatch()
    assert footer._startup_stopwatch_active is False


def test_bgcmd_badges_appear_alongside_stopwatch() -> None:
    """Background command counts render alongside the stopwatch badge."""
    footer = KeybindingFooter()
    footer._bgcmd_running_count = 2
    footer._bgcmd_done_count = 1
    plain = footer._get_status_text().plain
    assert "⏱" in plain
    assert "starting" in plain
    assert "[*2]" in plain
    assert "[✓1]" in plain
