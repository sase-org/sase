"""Tests for the startup stopwatch in KeybindingFooter."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.keybinding_footer import (
    _STOPWATCH_BG_FLASH_OFF,
    _STOPWATCH_BG_FLASH_ON,
    _STOPWATCH_BG_NORMAL,
    _STOPWATCH_BG_ORANGE,
    _STOPWATCH_BG_RED,
    _STOPWATCH_BG_YELLOW,
    _STOPWATCH_FG_DARK,
    _STOPWATCH_FG_LIGHT,
    _STOPWATCH_FLASH_PERIOD_TICKS,
    _STOPWATCH_GLYPH_FRAMES,
    _STOPWATCH_TIER_FLASH_SECS,
    _STOPWATCH_TIER_ORANGE_SECS,
    _STOPWATCH_TIER_RED_SECS,
    _STOPWATCH_TIER_YELLOW_SECS,
    KeybindingFooter,
)


def _has_any_frame_glyph(plain: str) -> bool:
    return any(frame in plain for frame in _STOPWATCH_GLYPH_FRAMES)


def _render_stopwatch(elapsed: float, *, frame: int = 0):
    footer = KeybindingFooter()
    footer._startup_elapsed = elapsed
    footer._stopwatch_frame = frame
    return footer._get_status_text()


def _label_span(text):
    for span in text.spans:
        if "starting" in text.plain[span.start : span.end]:
            return span
    raise AssertionError("missing startup label span")


def _label_is_bold(text) -> bool:
    return str(_label_span(text).style).startswith("bold ")


def _assert_stopwatch_style(
    elapsed: float,
    *,
    expected_bg: str,
    expected_fg: str,
    emphasized: bool = False,
    frame: int = 0,
) -> None:
    text = _render_stopwatch(elapsed, frame=frame)
    assert len(text.spans) == 4
    label_span, *stopwatch_spans = text.spans
    assert text.plain[label_span.start : label_span.end].strip() == "AXE"
    assert all(expected_bg in str(span.style) for span in stopwatch_spans)
    assert all(expected_fg in str(span.style) for span in stopwatch_spans)
    assert _label_is_bold(text) is emphasized


def test_default_state_shows_stopwatch() -> None:
    """A freshly instantiated footer renders the purple stopwatch badge."""
    footer = KeybindingFooter()
    assert footer._startup_stopwatch_active is True
    text = footer._get_status_text()
    assert _has_any_frame_glyph(text.plain)
    assert "starting" in text.plain
    assert text.plain.startswith(" AXE ")


def test_elapsed_formatting_one_decimal() -> None:
    """Elapsed time is rendered with one decimal place (rounded)."""
    footer = KeybindingFooter()
    footer._startup_elapsed = 2.4
    assert "2.4s" in footer._get_status_text().plain

    footer._startup_elapsed = 12.75
    assert "12.8s" in footer._get_status_text().plain

    footer._startup_elapsed = 0.1
    assert "0.1s" in footer._get_status_text().plain


@pytest.mark.parametrize(
    ("elapsed", "expected_bg", "expected_fg", "emphasized"),
    [
        (1.0, _STOPWATCH_BG_NORMAL, _STOPWATCH_FG_LIGHT, False),
        (
            _STOPWATCH_TIER_YELLOW_SECS - 0.1,
            _STOPWATCH_BG_NORMAL,
            _STOPWATCH_FG_LIGHT,
            False,
        ),
        (
            _STOPWATCH_TIER_YELLOW_SECS,
            _STOPWATCH_BG_YELLOW,
            _STOPWATCH_FG_DARK,
            False,
        ),
        (
            _STOPWATCH_TIER_ORANGE_SECS - 0.1,
            _STOPWATCH_BG_YELLOW,
            _STOPWATCH_FG_DARK,
            False,
        ),
        (
            _STOPWATCH_TIER_ORANGE_SECS,
            _STOPWATCH_BG_ORANGE,
            _STOPWATCH_FG_DARK,
            False,
        ),
        (
            _STOPWATCH_TIER_RED_SECS - 0.1,
            _STOPWATCH_BG_ORANGE,
            _STOPWATCH_FG_DARK,
            False,
        ),
        (
            _STOPWATCH_TIER_RED_SECS,
            _STOPWATCH_BG_RED,
            _STOPWATCH_FG_LIGHT,
            False,
        ),
        (
            _STOPWATCH_TIER_FLASH_SECS - 0.1,
            _STOPWATCH_BG_RED,
            _STOPWATCH_FG_LIGHT,
            False,
        ),
        (
            _STOPWATCH_TIER_FLASH_SECS,
            _STOPWATCH_BG_FLASH_ON,
            _STOPWATCH_FG_LIGHT,
            True,
        ),
    ],
)
def test_stopwatch_tier_boundaries(
    elapsed: float,
    expected_bg: str,
    expected_fg: str,
    emphasized: bool,
) -> None:
    """The startup badge escalates color and contrast at each threshold."""
    _assert_stopwatch_style(
        elapsed,
        expected_bg=expected_bg,
        expected_fg=expected_fg,
        emphasized=emphasized,
    )


def test_flash_tier_alternates_background_and_emphasizes_label() -> None:
    """The stuck-startup tier pulses red and bolds the entire badge."""
    backgrounds = set()
    elapsed = _STOPWATCH_TIER_FLASH_SECS + 1.0
    for frame in range(_STOPWATCH_FLASH_PERIOD_TICKS * 2):
        text = _render_stopwatch(elapsed, frame=frame)
        styles = [str(span.style) for span in text.spans]
        if any(_STOPWATCH_BG_FLASH_ON in style for style in styles):
            backgrounds.add(_STOPWATCH_BG_FLASH_ON)
        if any(_STOPWATCH_BG_FLASH_OFF in style for style in styles):
            backgrounds.add(_STOPWATCH_BG_FLASH_OFF)

    assert backgrounds == {_STOPWATCH_BG_FLASH_ON, _STOPWATCH_BG_FLASH_OFF}
    assert _label_is_bold(_render_stopwatch(elapsed, frame=0)) is True
    assert _label_is_bold(_render_stopwatch(_STOPWATCH_TIER_RED_SECS)) is False


def test_flash_background_participates_in_status_signature() -> None:
    """A flash phase change repaints even when elapsed text and glyph match."""
    footer = KeybindingFooter()
    footer._startup_elapsed = _STOPWATCH_TIER_FLASH_SECS + 1.0
    footer._stopwatch_frame = 0
    flash_on = footer._status_signature()

    footer._stopwatch_frame = (
        _STOPWATCH_FLASH_PERIOD_TICKS + len(_STOPWATCH_GLYPH_FRAMES) - 1
    )
    flash_off = footer._status_signature()

    assert footer._stopwatch_frame % len(_STOPWATCH_GLYPH_FRAMES) == 0
    assert flash_on != flash_off


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


def test_baseline_stopwatch_color_distinct_from_axe_pills() -> None:
    """Regression guard: normal startup stays visually distinct from AXE pills."""
    axe_pill_backgrounds = {
        "rgb(0,191,255)",  # RESTARTING
        "rgb(255,255,0)",  # STARTING
        "rgb(255,165,0)",  # STOPPING
        "green",  # RUNNING
        "red",  # STOPPED
    }
    assert _STOPWATCH_BG_NORMAL not in axe_pill_backgrounds
