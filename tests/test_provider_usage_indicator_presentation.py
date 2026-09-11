"""Compact provider-usage top-bar presentation tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
    usage_indicator_open_provider,
    usage_indicator_tooltip_lines,
)
from sase.ace.tui.widgets._usage_indicator_format import format_usage_percent_text
from sase.ace.tui.widgets._usage_indicator_palette import (
    _usage_badge_surface_color,
    _usage_gap_surface_color,
    usage_divider_style,
    usage_neutral_color,
    usage_percent_color,
    usage_rejected_style,
    usage_zero_value_style,
)
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._usage_view_helpers import usage_provider, usage_window

FROZEN_NOW = 1_800_000_000.0

_CONSOLE = Console(width=240)


def _rendered_segments(text: Text) -> list[tuple[str, Style | None]]:
    """Return the fully resolved (base + span) style for each rendered run."""
    return [(segment.text, segment.style) for segment in text.render(_CONSOLE)]


def _segments_with_offsets(text: Text) -> list[tuple[int, int, str, Style | None]]:
    offset = 0
    result: list[tuple[int, int, str, Style | None]] = []
    for segment in text.render(_CONSOLE):
        length = len(segment.text)
        if length:
            result.append((offset, offset + length, segment.text, segment.style))
        offset += length
    return result


def _style_for(text: Text, token: str) -> Style:
    """Return the resolved style of the one segment rendering exactly *token*."""
    matches = [
        style for rendered, style in _rendered_segments(text) if rendered == token
    ]
    assert len(matches) == 1, (
        f"expected exactly one {token!r} segment in {text.plain!r}"
    )
    style = matches[0]
    assert style is not None
    return style


def _style_at_token(text: Text, token: str, *, occurrence: int = 0) -> Style:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.plain.find(token, cursor)
        assert start >= 0, f"missing {token!r} occurrence {occurrence}"
        cursor = start + len(token)
    for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
        if seg_start <= start < seg_end:
            assert style is not None
            return style
    raise AssertionError(f"no style for {token!r} in {text.plain!r}")


def _style_at_offset(text: Text, offset: int) -> Style:
    for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
        if seg_start <= offset < seg_end:
            assert style is not None
            return style
    raise AssertionError(f"no style at offset {offset} in {text.plain!r}")


def _pipe_styles(text: Text) -> list[Style]:
    styles: list[Style] = []
    for index, character in enumerate(text.plain):
        if character != "|":
            continue
        for seg_start, seg_end, _rendered, style in _segments_with_offsets(text):
            if seg_start <= index < seg_end:
                assert style is not None
                styles.append(style)
                break
    return styles


def _assert_style_run(
    text: Text,
    run: str,
    expected: Style,
    *,
    occurrence: int = 0,
) -> tuple[int, int]:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.plain.find(run, cursor)
        assert start >= 0, f"missing {run!r} occurrence {occurrence}"
        cursor = start + len(run)
    end = start + len(run)
    for offset in range(start, end):
        assert _style_at_offset(text, offset) == expected
    return start, end


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    stripped = value.lstrip("#")
    return tuple(int(stripped[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a) + 0.05
    lb = _relative_luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def _scope(
    *,
    kind: str,
    product: str | None = None,
    family: str | None = None,
    model_ids: tuple[str, ...] = (),
    vendor_label: str | None = None,
    vendor_id: str | None = None,
) -> dict[str, object]:
    return {
        "kind": kind,
        "product": product,
        "family": family,
        "model_ids": list(model_ids),
        "vendor_label": vendor_label,
        "vendor_id": vendor_id,
    }


def _entry(
    *,
    provider: str = "claude",
    window_key: str = "weekly",
    window_label: str = "Week - all",
    weekly_all: bool = True,
    period_kind: str = "weekly",
    duration_seconds: float | None = 604_800.0,
    scope: dict[str, object] | None = None,
    remaining_percent: float = 62.0,
    freshness: str = "fresh",
    reset_state: str = "future",
    seconds_until_reset: float | None = 273_840.0,
    resets_at: float | None = FROZEN_NOW + 273_840.0,
    vendor_state: str = "allowed",
    window_attention: str = "none",
    display_attention: str = "none",
    collector_problem: bool = False,
    policy_source: str = "weekly_all",
) -> dict[str, object]:
    return {
        "provider": provider,
        "context_ref": f"{provider}:default:1",
        "window_key": window_key,
        "window_label": window_label,
        "effective_policy": {"kind": "always"},
        "policy_source": policy_source,
        "weekly_all": weekly_all,
        "period": {"kind": period_kind, "duration_seconds": duration_seconds},
        "scope": scope or _scope(kind="all_models"),
        "used_percent": max(0.0, 100.0 - remaining_percent),
        "remaining_percent": remaining_percent,
        "exceeded_by_percent": None,
        "freshness": freshness,
        "reset_state": reset_state,
        "seconds_until_reset": seconds_until_reset,
        "resets_at": resets_at,
        "duration_seconds": duration_seconds,
        "period_start": None,
        "age_seconds": 30.0,
        "observed_at": FROZEN_NOW - 30.0,
        "vendor_state": vendor_state,
        "window_attention": window_attention,
        "display_attention": display_attention,
        "collector_problem": collector_problem,
    }


def _groups(*entries: dict[str, object], dark: bool = True):
    return usage_indicator_groups(entries, dark=dark, now=FROZEN_NOW)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        pytest.param(_entry(), "🎭 62% 3d4h", id="weekly-all-default"),
        pytest.param(
            _entry(
                window_key="session",
                window_label="Claude five-hour session",
                weekly_all=False,
                period_kind="session",
                duration_seconds=None,
                scope=_scope(kind="all_models", product="claude"),
                remaining_percent=18.0,
                seconds_until_reset=7_740.0,
                resets_at=FROZEN_NOW + 7_740.0,
            ),
            "🎭 5h 18% 2h9m",
            id="session-all",
        ),
        pytest.param(
            _entry(
                window_key="weekly:claude-fable-5",
                window_label="Claude weekly Fable",
                weekly_all=False,
                period_kind="weekly",
                duration_seconds=None,
                scope=_scope(
                    kind="product",
                    product="claude",
                    model_ids=("claude-fable-5",),
                ),
                remaining_percent=7.0,
                seconds_until_reset=115_200.0,
                resets_at=FROZEN_NOW + 115_200.0,
            ),
            "🎭 fable 7% 1d8h",
            id="weekly-model",
        ),
        pytest.param(
            _entry(
                provider="grok",
                window_key="included_monthly",
                window_label="Grok included monthly allowance",
                weekly_all=False,
                period_kind="monthly",
                duration_seconds=None,
                scope=_scope(kind="all_models"),
                remaining_percent=44.0,
                seconds_until_reset=112_200.0,
                resets_at=FROZEN_NOW + 112_200.0,
            ),
            "🛰️ mo 44% 1d7h",
            id="monthly-all",
        ),
        pytest.param(
            _entry(
                provider="codex",
                window_key="fast:secondary",
                window_label="Fast",
                weekly_all=False,
                period_kind="duration",
                duration_seconds=18_000.0,
                scope=_scope(kind="unknown", vendor_label="Fast"),
                remaining_percent=12.0,
                seconds_until_reset=7_740.0,
                resets_at=FROZEN_NOW + 7_740.0,
            ),
            "🤖 Fast/5h/scope? 12% 2h9m",
            id="unknown-scope",
        ),
    ],
)
def test_compact_window_names(entry: dict[str, object], expected: str) -> None:
    segment = build_usage_indicator_segment(_groups(entry))

    assert segment.plain.strip() == expected


def test_grouped_default_first_text_order_icons_gaps_and_parentheses() -> None:
    all_model = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
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
    codex = _entry(
        provider="codex",
        window_key="weekly",
        remaining_percent=81.0,
        seconds_until_reset=439_200.0,
        resets_at=FROZEN_NOW + 439_200.0,
        display_attention="low",
    )

    segment = build_usage_indicator_segment(_groups(codex, session, fable, all_model))

    assert segment.plain == (
        "  🎭 (62% 3d4h | fable 7% 1d8h | 5h 18% 2h9m)  🤖 81% 5d2h  "
    )
    assert segment.plain.count("🎭") == 1
    assert segment.plain.count("🤖") == 1
    assert segment.plain.count("|") == 2
    assert ")  🤖" in segment.plain
    assert "⚠" not in segment.plain


def test_hidden_default_starts_with_named_extra() -> None:
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

    segment = build_usage_indicator_segment(_groups(fable))

    assert segment.plain.strip() == "🎭 fable 7% 1d8h"
    assert "|" not in segment.plain


def test_multiple_default_classified_entries_keep_lowest_key_unnamed() -> None:
    later = _entry(window_key="weekly:b", remaining_percent=55.0)
    anchor = _entry(window_key="weekly:a", remaining_percent=62.0)

    segment = build_usage_indicator_segment(_groups(later, anchor))

    assert segment.plain == "  🎭 (62% 3d4h | wk/all 55% 3d4h)  "


def test_colliding_compact_names_receive_stable_key_suffixes() -> None:
    first = _entry(
        window_key="fable-a",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=9.0,
    )
    second = _entry(
        window_key="fable-b",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=8.0,
    )

    segment = build_usage_indicator_segment(_groups(second, first))

    assert "fable [fable-a] 9%" in segment.plain
    assert "fable [fable-b] 8%" in segment.plain


def test_names_normalize_controls_and_structural_pipes() -> None:
    entry = _entry(
        provider="codex",
        window_key="fast",
        weekly_all=False,
        period_kind="duration",
        duration_seconds=18_000.0,
        scope=_scope(kind="unknown", vendor_label="Fast|\nTier\tA"),
        remaining_percent=12.0,
        seconds_until_reset=7_740.0,
        resets_at=FROZEN_NOW + 7_740.0,
    )

    segment = build_usage_indicator_segment(_groups(entry))

    assert "Fast/ Tier A/5h/scope? 12%" in segment.plain
    assert segment.plain.count("|") == 0


def test_vendor_rejected_window_shows_marker_before_percentage() -> None:
    entry = _entry(
        provider="grok",
        remaining_percent=4.0,
        vendor_state="rejected",
        display_attention="rejected",
    )

    segment = build_usage_indicator_segment(_groups(entry))

    assert segment.plain.strip() == "🛰️ ! 4% 3d4h"


def test_collector_problem_entry_has_no_warning_marker_but_keeps_tooltip_prose() -> (
    None
):
    entry = _entry(
        provider="codex",
        remaining_percent=50.0,
        collector_problem=True,
        vendor_state="rejected",
        display_attention="collection_problem",
    )
    groups = _groups(entry)

    segment = build_usage_indicator_segment(groups)
    tooltip = usage_indicator_tooltip_lines(groups)

    assert segment.plain.strip() == "🤖 ! 50% 3d4h"
    assert "⚠" not in segment.plain
    assert any("collector is currently failing" in line for line in tooltip)


def test_collector_only_state_produces_no_group_or_overflow_count() -> None:
    groups = usage_indicator_groups((), dark=True, now=FROZEN_NOW)

    assert groups == ()
    assert build_usage_indicator_segment(groups).plain == ""
    assert usage_indicator_tooltip_lines(groups) == ()


def test_stale_unknown_age_passed_unknown_reset_and_percent_edges() -> None:
    stale = _entry(remaining_percent=62.0, freshness="stale")
    unknown_age = _entry(remaining_percent=62.0, freshness="unknown")
    passed = _entry(
        remaining_percent=62.0,
        reset_state="passed",
        seconds_until_reset=0.0,
        resets_at=FROZEN_NOW - 10.0,
    )
    unknown_reset = _entry(
        remaining_percent=62.0,
        reset_state="unknown",
        seconds_until_reset=None,
        resets_at=None,
    )

    assert build_usage_indicator_segment(_groups(stale)).plain.strip() == "🎭 62% 3d4h"
    assert build_usage_indicator_segment(_groups(unknown_age)).plain.strip() == (
        "🎭 62% 3d4h"
    )
    assert build_usage_indicator_segment(_groups(passed)).plain.strip() == (
        "🎭 ?% 0h0m↻"
    )
    assert build_usage_indicator_segment(_groups(unknown_reset)).plain.strip() == (
        "🎭 62% ?"
    )
    assert format_usage_percent_text(0.0) == "0%"
    assert format_usage_percent_text(0.4) == "<1%"
    assert format_usage_percent_text(100.0) == "100%"


def test_stale_tooltip_explains_uncertainty_without_a_visible_marker() -> None:
    stale = _entry(remaining_percent=62.0, freshness="stale")
    unknown_age = _entry(
        window_key="session",
        weekly_all=False,
        period_kind="session",
        duration_seconds=None,
        remaining_percent=42.0,
        freshness="unknown",
    )
    groups = _groups(stale, unknown_age)
    segment = build_usage_indicator_segment(groups)
    tooltip = usage_indicator_tooltip_lines(groups)

    assert "~" not in segment.plain
    assert all("~" not in line for line in tooltip)
    assert "freshness: stale" in tooltip
    assert "freshness: unknown" in tooltip
    assert (
        sum("last observed capacity; it may be out of date" in line for line in tooltip)
        == 2
    )


def test_countdown_boundary_values() -> None:
    def _countdown(seconds: float) -> str:
        entry = _entry(
            provider="claude",
            remaining_percent=62.0,
            seconds_until_reset=seconds,
            resets_at=FROZEN_NOW + seconds,
        )
        segment = build_usage_indicator_segment(_groups(entry))
        return segment.plain.strip().rsplit(" ", 1)[-1]

    assert _countdown(59.0) == "0h1m"
    assert _countdown(60.0) == "0h1m"
    assert _countdown(3_599.0) == "0h59m"
    assert _countdown(3_600.0) == "1h0m"
    assert _countdown(86_399.0) == "23h59m"
    assert _countdown(86_400.0) == "1d0h"


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

    assert segment.plain.count("|") == 2
    punctuation_offsets = [
        index for index, character in enumerate(segment.plain) if character in "()|"
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

    provider_gap_index = segment.plain.find(")  🤖") + 1
    gap_style = _style_at_token(
        segment, " ", occurrence=segment.plain[: provider_gap_index + 1].count(" ")
    )
    assert gap_style.bgcolor is not None
    assert (
        gap_style.bgcolor.get_truecolor().hex
        == _usage_gap_surface_color(dark=dark).lower()
    )


def test_partial_overflow_keeps_balanced_parentheses_and_hidden_total() -> None:
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
    groups = _groups(default, fable, session, codex)
    expected = "  🎭 (62% 3d4h | fable 7% 1d8h)  +2  "

    segment = build_usage_indicator_segment(groups, budget=cell_len(expected))

    assert segment.plain == expected
    assert len(_pipe_styles(segment)) == 1
    assert segment.plain.count("(") == segment.plain.count(")") == 1


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

    assert len(_pipe_styles(segment)) == 1
    assert _pipe_styles(segment)[0].color is not None
    assert (
        _pipe_styles(segment)[0].color.get_truecolor().hex
        == usage_neutral_color(dark=True).lower()
    )


def test_budget_packing_falls_back_through_the_full_ladder() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    groups = _groups(grok, codex, claude)

    full = build_usage_indicator_segment(groups)
    assert cell_len(full.plain) == full.cell_len

    overflow = build_usage_indicator_segment(groups, budget=full.cell_len - 1)
    assert overflow.cell_len <= full.cell_len - 1
    assert overflow.plain.strip().endswith("+1")
    assert "🛰️" in overflow.plain

    count_only = build_usage_indicator_segment(groups, budget=cell_len("  usage 3  "))
    assert count_only.plain == "  usage 3  "

    padded_total = build_usage_indicator_segment(groups, budget=cell_len("  3  "))
    assert padded_total.plain == "  3  "

    micro = build_usage_indicator_segment(groups, budget=cell_len(" 3 "))
    assert micro.plain == " 3 "

    bare = build_usage_indicator_segment(groups, budget=1)
    assert bare.plain == "3"
    assert build_usage_indicator_segment(groups, budget=0).plain == ""


def test_fallback_ladder_uses_ellipsis_when_total_digits_do_not_fit() -> None:
    groups = _groups(
        *(_entry(provider=f"p{index}", remaining_percent=62.0) for index in range(12))
    )

    assert build_usage_indicator_segment(groups, budget=1).plain == "…"


def test_provider_badge_requires_owned_outer_margin() -> None:
    groups = _groups(_entry(provider="claude", remaining_percent=62.0))
    full = build_usage_indicator_segment(groups)

    segment = build_usage_indicator_segment(groups, budget=full.cell_len - 1)

    assert full.plain == "  🎭 62% 3d4h  "
    assert "🎭" not in segment.plain


def test_open_provider_prefers_first_ranked_group() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    claude = _entry(provider="claude", remaining_percent=62.0)

    assert usage_indicator_open_provider(_groups(claude, grok)) == "grok"
    assert usage_indicator_open_provider(()) is None


def test_unknown_provider_falls_back_to_id_marker() -> None:
    entry = _entry(provider="acme", remaining_percent=62.0)

    segment = build_usage_indicator_segment(_groups(entry))

    assert segment.plain.strip() == "ACME 62% 3d4h"


@pytest.mark.parametrize("dark", [True, False])
def test_overflow_and_fallback_disclosure_render_bold_neutral_on_badge_surface(
    dark: bool,
) -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    groups = _groups(grok, codex, claude, dark=dark)
    full = build_usage_indicator_segment(groups, dark=dark)
    neutral = usage_neutral_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    overflow = build_usage_indicator_segment(
        groups, budget=full.cell_len - 1, dark=dark
    )
    plus_one_style = _style_for(overflow, "+1")

    count_only = build_usage_indicator_segment(
        groups, budget=cell_len("  usage 3  "), dark=dark
    )
    count_style = _style_for(count_only, "usage 3")

    for style in (plus_one_style, count_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


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


def _indicator_snapshot(*windows: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "claude",
                used_percent=10.0,
                remaining_percent=90.0,
                attention={
                    "kind": "none",
                    "provider": "claude",
                    "window_key": "weekly",
                },
                windows=list(windows),
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def _weekly_usage_window(
    *,
    key: str,
    label: str,
    remaining_percent: float,
    resets_at: float,
    applicability: dict[str, object],
) -> dict[str, object]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=max(0.0, 100.0 - remaining_percent),
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability=applicability,
    )
    window["duration_seconds"] = 604_800.0
    return window


def test_real_projection_selection_boundary_and_renderer_integration() -> None:
    snapshot = _indicator_snapshot(
        _weekly_usage_window(
            key="weekly",
            label="Week",
            remaining_percent=90.0,
            resets_at=FROZEN_NOW + 1_000.0,
            applicability={"kind": "account"},
        ),
        _weekly_usage_window(
            key="fable-1999",
            label="Fable 19.99",
            remaining_percent=19.99,
            resets_at=FROZEN_NOW + 2_000.0,
            applicability={"kind": "models", "model_ids": ["claude-fable-5"]},
        ),
        _weekly_usage_window(
            key="fable-20",
            label="Fable 20",
            remaining_percent=20.0,
            resets_at=FROZEN_NOW + 3_000.0,
            applicability={"kind": "models", "model_ids": ["claude-fable-5"]},
        ),
    )

    projection = provider_usage_project_indicator(
        snapshot,
        indicator={
            "default": {"below_remaining_percent": 20},
            "weekly_all": "always",
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert [entry["window_key"] for entry in projection.entries] == [
        "fable-1999",
        "weekly",
    ]
    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=FROZEN_NOW)
    )
    assert "🎭 (90%" in segment.plain
    assert "fable 19%" in segment.plain
    assert "20%" not in segment.plain

    override_projection = provider_usage_project_indicator(
        snapshot,
        indicator={
            "default": {"below_remaining_percent": 20},
            "weekly_all": "always",
            "providers": {"claude": {"windows": {"fable-20": "always"}}},
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    override_segment = build_usage_indicator_segment(
        usage_indicator_groups(override_projection.entries, dark=True, now=FROZEN_NOW)
    )
    assert "fable [fable-1999] 19%" in override_segment.plain
    assert "fable [fable-20] 20%" in override_segment.plain

    always_projection = provider_usage_project_indicator(
        snapshot,
        indicator={"default": "always"},
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert {entry["window_key"] for entry in always_projection.entries} == {
        "weekly",
        "fable-1999",
        "fable-20",
    }

    never_projection = provider_usage_project_indicator(
        snapshot,
        indicator={"enabled": False},
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert never_projection.entries == ()
    assert (
        build_usage_indicator_segment(
            usage_indicator_groups(never_projection.entries, dark=True, now=FROZEN_NOW)
        ).plain
        == ""
    )
