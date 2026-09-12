"""Color, style, and contrast tests for the compact provider-usage header.

Text, grouping, and tooltip coverage lives in
``test_provider_usage_indicator_presentation.py``. Budget packing,
overflow, and projection integration live in
``test_provider_usage_indicator_presentation_layout.py``.
"""

from __future__ import annotations

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
    _entry,
    _groups,
    _dot_styles,
    _scope,
    _style_at_offset,
    _style_at_token,
    _style_for,
)


def test_ten_bucket_percent_boundaries_use_the_documented_palettes() -> None:
    expected_dark = (
        "#FF5F6D",
        "#FF805F",
        "#FFA552",
        "#EBC04F",
        "#CED44C",
        "#AADC64",
        "#78DB8D",
        "#4CD4B0",
        "#48CCD0",
        "#65C3ED",
    )
    for decile, color in enumerate(expected_dark):
        assert usage_percent_color(decile * 10, dark=True) == color
        assert usage_percent_color(decile * 10 + 9.99, dark=True) == color
    assert usage_percent_color(100, dark=True) == expected_dark[9]
    assert usage_percent_color(0, dark=False) == "#A22534"
    assert usage_percent_color(95, dark=False) == "#006381"


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
    entry = _entry(remaining_percent=0.0)
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

    zero_run = "0% 3d4h"
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
def test_named_and_rejected_zero_neighbors_keep_normal_badge_surface(
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
    badge_surface = _usage_badge_surface_color(dark=dark)

    assert segment.plain.strip() == "🛰️ grok-preview ! 0% 3d4h"
    for token in ("grok-preview", "!"):
        style = _style_at_token(segment, token)
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()
    _assert_style_run(
        segment,
        "0% 3d4h",
        Style.parse(usage_zero_value_style(dark=dark)),
    )


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
            "🛰️ ! 0% 3d4h",
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
        colors = [usage_percent_color(decile * 10.0, dark=dark) for decile in range(10)]
        colors.append(usage_neutral_color(dark=dark))
        colors.append(usage_rejected_style(dark=dark).rsplit(" ", 1)[-1])
        for color in colors:
            assert _contrast_ratio(color, badge_surface) >= 4.5, (dark, color)


def test_zero_percent_inverted_style_meets_minimum_contrast() -> None:
    for dark in (True, False):
        zero_background = usage_percent_color(0, dark=dark)
        badge_foreground = _usage_badge_surface_color(dark=dark)
        assert _contrast_ratio(badge_foreground, zero_background) >= 4.5
