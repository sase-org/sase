"""Low-level palette, axis, and braille-canvas tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sase.telemetry.render import (
    CATEGORICAL_COLORS,
    STATUS_COLORS,
    BrailleCanvas,
    categorical_color,
    format_bytes,
    format_duration,
    format_percentage,
    format_recording_started,
    format_tokens,
    format_value,
    validate_palette,
)


def test_palette_is_valid_stable_and_reserves_status_colors() -> None:
    validate_palette()

    assert set(CATEGORICAL_COLORS).isdisjoint(STATUS_COLORS.values())
    assert categorical_color("openai") == "#AF87FF"
    assert categorical_color("anthropic") == "#5FAFFF"
    assert categorical_color("openai") == categorical_color("openai")


@pytest.mark.parametrize(
    ("formatter", "value", "expected"),
    [
        (format_duration, 0.125, "125ms"),
        (format_duration, 65, "1m05s"),
        (format_tokens, 12_500, "12k"),
        (format_percentage, 5.25, "5.2%"),
        (format_bytes, 1_572_864, "1.5MiB"),
        (format_value, 1_250, "1.2k"),
    ],
)
def test_humanized_axis_formatters(
    formatter: object, value: float, expected: str
) -> None:
    assert callable(formatter)
    assert formatter(value) == expected  # type: ignore[operator]


def test_recording_started_empty_state_is_clock_independent() -> None:
    started = datetime(2026, 7, 17, 12, 30, tzinfo=UTC)

    assert format_recording_started(started) == (
        "no samples in range — telemetry began recording 2026-07-17 12:30 UTC"
    )


def test_braille_canvas_dot_mapping_golden() -> None:
    canvas = BrailleCanvas(2, 1)
    for point in ((0, 0), (1, 1), (2, 2), (3, 3)):
        canvas.set(*point)

    assert canvas.render().plain == "⠑⢄"


def test_braille_polyline_is_clipped_and_deterministic() -> None:
    canvas = BrailleCanvas(4, 2)
    canvas.draw_polyline([(-100, -100), (2, 5), (100, 100)])

    assert canvas.render().plain == "⢣   \n ⠓⠤⣀"
