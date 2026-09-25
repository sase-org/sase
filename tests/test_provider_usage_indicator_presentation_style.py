"""Color, style, and contrast tests for the compact provider-usage header.

Text, grouping, and tooltip coverage lives in
``test_provider_usage_indicator_presentation.py``. Budget packing,
overflow, and projection integration live in
``test_provider_usage_indicator_presentation_layout.py``.
"""

from __future__ import annotations

import math

import pytest
from rich.style import Style

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
)
from sase.ace.tui.widgets._usage_indicator_palette import (
    _usage_badge_surface_color,
    _usage_gap_surface_color,
    usage_divider_style,
    usage_neutral_color,
    usage_percent_color,
    usage_rejected_style,
    usage_zero_value_style,
)
from tests._provider_usage_indicator_presentation_helpers import (
    FROZEN_NOW,
    _assert_style_run,
    _contrast_ratio,
    _dot_styles,
    _entry,
    _groups,
    _scope,
    _style_at_offset,
    _style_at_token,
    _style_for,
)

_BUCKET_RANGE_CASES = (
    (range(1, 11), "#FF5F6D", "#A22534"),
    (range(11, 21), "#FF805F", "#A03620"),
    (range(21, 31), "#FFA552", "#8C480E"),
    (range(31, 41), "#EBC04F", "#775800"),
    (range(41, 51), "#CED44C", "#5F6500"),
    (range(51, 61), "#AADC64", "#456C1B"),
    (range(61, 71), "#78DB8D", "#206F3C"),
    (range(71, 81), "#4CD4B0", "#006E56"),
    (range(81, 91), "#48CCD0", "#006C6C"),
    (range(91, 101), "#65C3ED", "#006381"),
)


def _theme_bucket_colors(*, dark: bool) -> tuple[str, ...]:
    return tuple(
        dark_color if dark else light_color
        for _integers, dark_color, light_color in _BUCKET_RANGE_CASES
    )


@pytest.mark.parametrize("dark", [True, False])
def test_positive_integer_percentages_fill_each_documented_bucket(
    dark: bool,
) -> None:
    expected_colors = _theme_bucket_colors(dark=dark)

    for integers, dark_color, light_color in _BUCKET_RANGE_CASES:
        expected_color = dark_color if dark else light_color
        for percent in integers:
            assert usage_percent_color(float(percent), dark=dark) == expected_color

    sampled = [
        usage_percent_color(float(percent), dark=dark) for percent in range(1, 101)
    ]
    assert len(set(sampled)) == 10
    assert [sampled.count(color) for color in expected_colors] == [10] * 10


@pytest.mark.parametrize("dark", [True, False])
def test_percent_color_boundaries_follow_the_displayed_integer(dark: bool) -> None:
    colors = _theme_bucket_colors(dark=dark)
    cases = (
        (9.0, colors[0]),
        (10.0, colors[0]),
        (10.99, colors[0]),
        (11.0, colors[1]),
        (20.0, colors[1]),
        (20.99, colors[1]),
        (21.0, colors[2]),
        (30.0, colors[2]),
        (30.99, colors[2]),
        (31.0, colors[3]),
        (40.0, colors[3]),
        (40.99, colors[3]),
        (41.0, colors[4]),
        (50.0, colors[4]),
        (50.99, colors[4]),
        (51.0, colors[5]),
        (60.0, colors[5]),
        (60.99, colors[5]),
        (61.0, colors[6]),
        (70.0, colors[6]),
        (70.99, colors[6]),
        (71.0, colors[7]),
        (80.0, colors[7]),
        (80.99, colors[7]),
        (81.0, colors[8]),
        (90.0, colors[8]),
        (90.99, colors[8]),
        (91.0, colors[9]),
    )

    for remaining_percent, expected_color in cases:
        assert usage_percent_color(remaining_percent, dark=dark) == expected_color


@pytest.mark.parametrize("dark", [True, False])
def test_percent_color_handles_zero_subpercent_clamping_and_nonfinite(
    dark: bool,
) -> None:
    colors = _theme_bucket_colors(dark=dark)

    cases = (
        (0.0, colors[0]),
        (-3.0, colors[0]),
        (0.4, colors[0]),
        (100.0, colors[9]),
        (130.0, colors[9]),
        (math.nan, colors[0]),
        (math.inf, colors[0]),
        (-math.inf, colors[0]),
    )

    for remaining_percent, expected_color in cases:
        assert usage_percent_color(remaining_percent, dark=dark) == expected_color


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize(
    ("remaining_percent", "percent_token", "bucket_index"),
    [
        pytest.param(10.0, "10%", 0, id="ten"),
        pytest.param(10.99, "10%", 0, id="ten-fraction"),
        pytest.param(11.0, "11%", 1, id="eleven"),
    ],
)
def test_rendered_positive_boundary_uses_displayed_percent_color(
    dark: bool,
    remaining_percent: float,
    percent_token: str,
    bucket_index: int,
) -> None:
    entry = _entry(
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=remaining_percent,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
    )
    segment = build_usage_indicator_segment(_groups(entry, dark=dark), dark=dark)
    expected_color = _theme_bucket_colors(dark=dark)[bucket_index]
    badge_surface = _usage_badge_surface_color(dark=dark)

    assert segment.plain.strip() == f"🎭 fable {percent_token} 1d8h"
    for token in ("fable", percent_token, "1d8h"):
        style = _style_at_token(segment, token)
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == expected_color.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_name_percent_and_countdown_share_bold_value_color(dark: bool) -> None:
    entry = _entry(
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
        display_attention="very_low",
    )
    segment = build_usage_indicator_segment(_groups(entry, dark=dark), dark=dark)
    bucket_color = usage_percent_color(7.0, dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    for token in ("fable", "7%", "1d8h"):
        style = _style_at_token(segment, token)
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == bucket_color.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_exact_zero_percent_uses_inverted_value_style(dark: bool) -> None:
    entry = _entry(
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=0.0,
    )
    segment = build_usage_indicator_segment(_groups(entry, dark=dark), dark=dark)
    exhausted_color = usage_percent_color(0, dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    zero_start = segment.plain.find("0%")
    assert zero_start >= 0
    zero_style = _style_at_token(segment, "0%")
    assert zero_style == Style.parse(usage_zero_value_style(dark=dark))
    assert zero_style.bold is True
    assert zero_style.dim is False
    assert zero_style.reverse is False
    assert zero_style.color is not None
    assert zero_style.color.get_truecolor().hex == badge_surface.lower()
    assert zero_style.bgcolor is not None
    assert zero_style.bgcolor.get_truecolor().hex == exhausted_color.lower()

    zero_run = "fable 0% 3d4h"
    zero_start, zero_end = _assert_style_run(
        segment,
        zero_run,
        Style.parse(usage_zero_value_style(dark=dark)),
    )

    for offset in (zero_start - 1, zero_end):
        adjacent_style = _style_at_offset(segment, offset)
        assert adjacent_style.bgcolor is not None
        assert adjacent_style.bgcolor.get_truecolor().hex != exhausted_color.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_named_rejected_zero_run_omits_marker_in_one_inverted_block(
    dark: bool,
) -> None:
    entry = _entry(
        provider="grok",
        window_key="weekly:grok-preview",
        weekly_all=False,
        scope=_scope(kind="product", product="grok", model_ids=("grok-preview",)),
        remaining_percent=0.0,
        vendor_state="rejected",
        display_attention="rejected",
    )
    segment = build_usage_indicator_segment(_groups(entry, dark=dark), dark=dark)
    exhausted_color = usage_percent_color(0, dark=dark)

    assert segment.plain.strip() == "🚀 grok-preview 0% 3d4h"
    start, end = _assert_style_run(
        segment,
        "grok-preview 0% 3d4h",
        Style.parse(usage_zero_value_style(dark=dark)),
    )

    for offset in (start - 1, end):
        adjacent_style = _style_at_offset(segment, offset)
        assert adjacent_style.bgcolor is not None
        assert adjacent_style.bgcolor.get_truecolor().hex != exhausted_color.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_rejected_zero_renders_identically_to_allowed_zero(dark: bool) -> None:
    rejected = _entry(
        provider="codex",
        remaining_percent=0.0,
        vendor_state="rejected",
        display_attention="rejected",
    )
    allowed = _entry(
        provider="codex",
        remaining_percent=0.0,
        vendor_state="allowed",
    )
    rejected_segment = build_usage_indicator_segment(
        _groups(rejected, dark=dark), dark=dark
    )
    allowed_segment = build_usage_indicator_segment(
        _groups(allowed, dark=dark), dark=dark
    )

    assert "!" not in rejected_segment.plain
    assert rejected_segment.plain == allowed_segment.plain
    assert rejected_segment.spans == allowed_segment.spans


@pytest.mark.parametrize("dark", [True, False])
def test_zero_and_healthy_windows_stay_separated_by_normal_divider(
    dark: bool,
) -> None:
    healthy = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
    exhausted = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=0.0,
    )
    segment = build_usage_indicator_segment(
        _groups(healthy, exhausted, dark=dark), dark=dark
    )

    assert segment.plain.strip() == "🎭 62% 3d4h · fable 0% 3d4h"
    assert _dot_styles(segment) == [Style.parse(usage_divider_style(dark=dark))]
    _assert_style_run(
        segment,
        "fable 0% 3d4h",
        Style.parse(usage_zero_value_style(dark=dark)),
    )
    healthy_style = _style_at_token(segment, "62%")
    assert healthy_style != Style.parse(usage_zero_value_style(dark=dark))


@pytest.mark.parametrize(
    ("entry", "expected", "percent_token", "zero_emphasized"),
    [
        pytest.param(
            _entry(remaining_percent=0.0), "🎭 0% 3d4h", "0%", True, id="zero"
        ),
        pytest.param(
            _entry(remaining_percent=-3.0),
            "🎭 0% 3d4h",
            "0%",
            True,
            id="negative-clamped-zero",
        ),
        pytest.param(
            _entry(remaining_percent=0.4),
            "🎭 <1% 3d4h",
            "<1%",
            False,
            id="subpercent",
        ),
        pytest.param(_entry(remaining_percent=7.0), "🎭 7% 3d4h", "7%", False, id="7"),
        pytest.param(
            _entry(remaining_percent=0.0, freshness="stale"),
            "🎭 0% 3d4h",
            "0%",
            True,
            id="stale-zero",
        ),
        pytest.param(
            _entry(
                provider="grok",
                remaining_percent=0.0,
                vendor_state="rejected",
                display_attention="rejected",
            ),
            "🚀 0% 3d4h",
            "0%",
            True,
            id="rejected-zero",
        ),
        pytest.param(
            _entry(
                remaining_percent=0.0,
                reset_state="passed",
                seconds_until_reset=0.0,
                resets_at=FROZEN_NOW - 10.0,
            ),
            "🎭 ?% 0h0m↻",
            "?%",
            False,
            id="passed-retained-zero",
        ),
        pytest.param(
            _entry(
                remaining_percent=0.0,
                reset_state="unknown",
                seconds_until_reset=None,
                resets_at=None,
            ),
            "🎭 0% ?",
            "0%",
            True,
            id="unknown-reset-zero",
        ),
    ],
)
def test_zero_percent_state_contract(
    entry: dict[str, object],
    expected: str,
    percent_token: str,
    zero_emphasized: bool,
) -> None:
    segment = build_usage_indicator_segment(_groups(entry))
    percent_style = _style_at_token(segment, percent_token)
    badge_surface = _usage_badge_surface_color(dark=True)
    exhausted_color = usage_percent_color(0, dark=True)

    assert segment.plain.strip() == expected
    assert percent_style.bgcolor is not None
    if zero_emphasized:
        assert percent_style.color is not None
        assert percent_style.color.get_truecolor().hex == badge_surface.lower()
        assert percent_style.bgcolor.get_truecolor().hex == exhausted_color.lower()
    else:
        assert percent_style.bgcolor.get_truecolor().hex == badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_stale_and_passed_values_use_bold_neutral_color(dark: bool) -> None:
    stale = _entry(remaining_percent=62.0, freshness="stale")
    unknown_age = _entry(remaining_percent=62.0, freshness="unknown")
    passed = _entry(
        remaining_percent=62.0,
        reset_state="passed",
        seconds_until_reset=0.0,
        resets_at=FROZEN_NOW - 10.0,
    )
    neutral = usage_neutral_color(dark=dark)

    for segment, tokens in (
        (
            build_usage_indicator_segment(_groups(stale, dark=dark), dark=dark),
            ("62%", "3d4h"),
        ),
        (
            build_usage_indicator_segment(_groups(unknown_age, dark=dark), dark=dark),
            ("62%", "3d4h"),
        ),
        (
            build_usage_indicator_segment(_groups(passed, dark=dark), dark=dark),
            ("?%", "0h0m↻"),
        ),
    ):
        for token in tokens:
            style = _style_at_token(segment, token)
            assert style.bold is True
            assert style.color is not None
            assert style.color.get_truecolor().hex == neutral.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_rejected_marker_renders_bold_on_badge_surface(dark: bool) -> None:
    entry = _entry(
        provider="grok",
        remaining_percent=4.0,
        vendor_state="rejected",
        display_attention="rejected",
    )
    segment = build_usage_indicator_segment(_groups(entry, dark=dark), dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    base_style = Style.parse(f"not bold not dim not reverse on {badge_surface}")
    rejected_style = _style_for(segment, "!")

    assert rejected_style == Style.combine(
        [base_style, Style.parse(usage_rejected_style(dark=dark))]
    )


@pytest.mark.parametrize("dark", [True, False])
def test_structural_punctuation_is_neutral_on_provider_badge_surface(
    dark: bool,
) -> None:
    default = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
    fable = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
        display_attention="very_low",
    )
    session = _entry(
        provider="claude",
        window_key="session",
        weekly_all=False,
        period_kind="session",
        duration_seconds=None,
        remaining_percent=18.0,
        seconds_until_reset=7_740.0,
        resets_at=FROZEN_NOW + 7_740.0,
        display_attention="low",
    )
    codex = _entry(provider="codex", remaining_percent=81.0)
    groups = _groups(default, fable, session, codex, dark=dark)
    segment = build_usage_indicator_segment(groups, dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)
    neutral = usage_neutral_color(dark=dark)

    assert segment.plain.count("·") == 2
    punctuation_offsets = [
        index for index, character in enumerate(segment.plain) if character == "·"
    ]
    assert punctuation_offsets
    for offset in punctuation_offsets:
        style = _style_at_offset(segment, offset)
        assert style.bold is False
        assert style.dim is False
        assert style.reverse is False
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()
        assert style == Style.parse(usage_divider_style(dark=dark))

    provider_gap_at = segment.plain.find("  🤖")
    assert provider_gap_at >= 0
    for offset in range(provider_gap_at, provider_gap_at + 2):
        gap_style = _style_at_offset(segment, offset)
        assert gap_style.bgcolor is not None
        assert (
            gap_style.bgcolor.get_truecolor().hex
            == _usage_gap_surface_color(dark=dark).lower()
        )


def test_neutral_final_window_colors_dividers_neutral() -> None:
    default = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
    stale = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=50.0,
        freshness="stale",
    )

    segment = build_usage_indicator_segment(_groups(default, stale))

    assert len(_dot_styles(segment)) == 1
    assert _dot_styles(segment)[0].color is not None
    assert (
        _dot_styles(segment)[0].color.get_truecolor().hex
        == usage_neutral_color(dark=True).lower()
    )


def test_defined_colors_meet_minimum_contrast_on_badge_surface() -> None:
    for dark in (True, False):
        badge_surface = _usage_badge_surface_color(dark=dark)
        sampled_bucket_colors = [
            usage_percent_color(float(percent), dark=dark)
            for percent in range(10, 101, 10)
        ]
        assert len(set(sampled_bucket_colors)) == 10

        checked_colors = [
            *sampled_bucket_colors,
            usage_neutral_color(dark=dark),
            usage_rejected_style(dark=dark).rsplit(" ", 1)[-1],
        ]
        for color in checked_colors:
            assert _contrast_ratio(color, badge_surface) >= 4.5, (dark, color)


def test_zero_percent_inverted_style_meets_minimum_contrast() -> None:
    for dark in (True, False):
        zero_background = usage_percent_color(0, dark=dark)
        badge_foreground = _usage_badge_surface_color(dark=dark)
        assert _contrast_ratio(badge_foreground, zero_background) >= 4.5
