"""Tests for the startup stopwatch in KeybindingFooter."""

from __future__ import annotations

from sase.ace.tui.widgets.keybinding_footer import (
    _STOPWATCH_BG_NORMAL,
    _STOPWATCH_BG_SLOW,
    _STOPWATCH_GLYPH_FRAMES,
    KeybindingFooter,
)


def _has_any_frame_glyph(plain: str) -> bool:
    return any(frame in plain for frame in _STOPWATCH_GLYPH_FRAMES)


def test_default_state_shows_stopwatch() -> None:
    """A freshly instantiated footer renders the purple stopwatch badge."""
    footer = KeybindingFooter()
    assert footer._startup_stopwatch_active is True
    text = footer._get_status_text()
    assert _has_any_frame_glyph(text.plain)
    assert "starting" in text.plain
    # Leading spaces before the frame glyph match the padded-badge convention.
    assert text.plain.startswith("  ")


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
    """Past the slow threshold the badge uses raspberry magenta instead of amethyst."""
    footer = KeybindingFooter()
    footer._startup_elapsed = 1.0
    normal_spans = footer._get_status_text().spans
    assert any(_STOPWATCH_BG_NORMAL in str(span.style) for span in normal_spans)

    footer._startup_elapsed = 15.0
    slow_spans = footer._get_status_text().spans
    assert any(_STOPWATCH_BG_SLOW in str(span.style) for span in slow_spans)


def test_end_transitions_to_real_status() -> None:
    """After end_startup_stopwatch(), the real AXE pill appears."""
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    assert footer._startup_stopwatch_active is False

    stopped = footer._get_status_text().plain
    assert not _has_any_frame_glyph(stopped)
    assert "STOPPED" in stopped

    footer._axe_running = True
    running = footer._get_status_text().plain
    assert not _has_any_frame_glyph(running)
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
    assert _has_any_frame_glyph(plain)
    assert "starting" in plain
    assert "[*2]" in plain
    assert "[✓1]" in plain


def test_frame_rotation_advances_per_tick() -> None:
    """Each stopwatch tick advances the frame index, cycling through all frames."""
    footer = KeybindingFooter()
    start_frame = footer._stopwatch_frame
    seen: set[int] = set()
    for _ in range(4):
        footer._on_stopwatch_tick()
        seen.add(footer._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES))
    assert footer._stopwatch_frame - start_frame >= 4
    assert seen == set(range(len(_STOPWATCH_GLYPH_FRAMES)))


def test_stopwatch_colors_distinct_from_axe_pills() -> None:
    """Regression guard: stopwatch bg colors must not collide with any AXE pill bg."""
    axe_pill_backgrounds = {
        "rgb(0,191,255)",  # RESTARTING
        "rgb(255,255,0)",  # STARTING
        "rgb(255,165,0)",  # STOPPING
        "green",  # RUNNING
        "red",  # STOPPED
    }
    assert _STOPWATCH_BG_NORMAL not in axe_pill_backgrounds
    assert _STOPWATCH_BG_SLOW not in axe_pill_backgrounds
