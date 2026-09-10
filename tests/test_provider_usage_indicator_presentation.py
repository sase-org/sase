"""Compact provider-usage top-bar presentation tests."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_badges,
    usage_indicator_open_provider,
    usage_indicator_tooltip_lines,
)
from sase.ace.tui.widgets._usage_indicator_format import format_usage_percent_text
from sase.ace.tui.widgets._usage_indicator_palette import (
    _usage_badge_surface_color,
    _usage_gap_surface_color,
    usage_neutral_color,
    usage_percent_color,
    usage_rejected_style,
    usage_warning_style,
)

FROZEN_NOW = 1_800_000_000.0

_CONSOLE = Console(width=200)


def _rendered_segments(text: Text) -> list[tuple[str, Style | None]]:
    """Return the fully resolved (base + span) style for each rendered run."""
    return [(segment.text, segment.style) for segment in text.render(_CONSOLE)]


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


def _badges(*entries: dict[str, object], providers=(), dark: bool = True):
    return usage_indicator_badges(entries, providers, dark=dark, now=FROZEN_NOW)


def test_weekly_all_model_window_omits_specifier() -> None:
    entry = _entry(provider="claude", remaining_percent=62.0)

    badges = _badges(entry)
    segment = build_usage_indicator_segment(badges)

    assert segment.plain.strip() == "🎭 62% 3d4h"


def test_claude_five_hour_session_uses_all_specifier() -> None:
    entry = _entry(
        provider="claude",
        window_key="session",
        window_label="Claude five-hour session",
        weekly_all=False,
        period_kind="session",
        duration_seconds=None,
        scope=_scope(kind="all_models", product="claude"),
        remaining_percent=18.0,
        seconds_until_reset=7_740.0,
        resets_at=FROZEN_NOW + 7_740.0,
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🎭 5h/all 18% 2h9m"


def test_claude_weekly_fable_uses_short_model_alias() -> None:
    entry = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        window_label="Claude weekly Fable",
        weekly_all=False,
        period_kind="weekly",
        duration_seconds=None,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🎭 wk/fable 7% 1d8h"


def test_grok_monthly_account_uses_all_specifier() -> None:
    entry = _entry(
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
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🛰️ mo/all 44% 1d7h"


def test_unknown_scope_vendor_label_leads_specifier() -> None:
    entry = _entry(
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
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🤖 Fast/5h/scope? 12% 2h9m"


def test_vendor_rejected_window_shows_marker() -> None:
    entry = _entry(
        provider="grok",
        weekly_all=True,
        remaining_percent=4.0,
        vendor_state="rejected",
        window_attention="rejected",
        display_attention="rejected",
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🛰️ ! 4% 3d4h"


def test_collector_problem_entry_shows_warning_marker() -> None:
    entry = _entry(provider="codex", remaining_percent=50.0, collector_problem=True)

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🤖 ⚠ 50% 3d4h"


def test_standalone_collector_failure_without_selected_window() -> None:
    providers = (
        {
            "provider": "grok",
            "collection_status": "error",
            "collection_reason": "vendor_drift",
            "diagnostic": None,
            "collector_health": {
                "state": "failing",
                "consecutive_failures": 5,
                "failing_since": FROZEN_NOW - 172_800.0,
                "last_success_at": FROZEN_NOW - 259_200.0,
            },
            "collector_problem": True,
        },
    )

    badges = _badges(providers=providers)
    segment = build_usage_indicator_segment(badges)
    tooltip_lines = usage_indicator_tooltip_lines(badges)

    assert segment.plain.strip() == "🛰️ ⚠"
    assert tooltip_lines[0] == "GROK - usage collection is failing"
    assert any("failing since: 2d ago" in line for line in tooltip_lines)
    assert any("last success: 3d ago" in line for line in tooltip_lines)


def test_stale_reading_appends_tilde_and_uses_neutral_style() -> None:
    entry = _entry(provider="claude", remaining_percent=62.0, freshness="stale")

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🎭 62%~ 3d4h"


def test_reset_passed_shows_question_percent_and_reset_glyph() -> None:
    entry = _entry(
        provider="claude",
        remaining_percent=62.0,
        reset_state="passed",
        seconds_until_reset=0.0,
        resets_at=FROZEN_NOW - 10.0,
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🎭 ?% 0h0m↻"


def test_missing_reset_shows_question_mark_countdown() -> None:
    entry = _entry(
        provider="claude",
        remaining_percent=62.0,
        reset_state="unknown",
        seconds_until_reset=None,
        resets_at=None,
    )

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "🎭 62% ?"


def test_countdown_boundary_values() -> None:
    def _countdown(seconds: float) -> str:
        entry = _entry(
            provider="claude",
            remaining_percent=62.0,
            seconds_until_reset=seconds,
            resets_at=FROZEN_NOW + seconds,
        )
        segment = build_usage_indicator_segment(_badges(entry))
        return segment.plain.strip().rsplit(" ", 1)[-1]

    assert _countdown(59.0) == "0h1m"
    assert _countdown(60.0) == "0h1m"
    assert _countdown(3_599.0) == "0h59m"
    assert _countdown(3_600.0) == "1h0m"
    assert _countdown(86_399.0) == "23h59m"
    assert _countdown(86_400.0) == "1d0h"


def test_ten_bucket_percent_boundaries_use_the_documented_dark_palette() -> None:
    expected = (
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
    for decile, color in enumerate(expected):
        assert usage_percent_color(decile * 10, dark=True) == color
        assert usage_percent_color(decile * 10 + 9.99, dark=True) == color
    assert usage_percent_color(100, dark=True) == expected[9]
    assert (
        len({usage_percent_color(decile * 10, dark=True) for decile in range(10)}) == 10
    )


def test_ten_bucket_percent_uses_a_distinct_light_theme_palette() -> None:
    assert usage_percent_color(0, dark=False) == "#A22534"
    assert usage_percent_color(95, dark=False) == "#006381"
    assert usage_percent_color(0, dark=False) != usage_percent_color(0, dark=True)


def test_multi_window_same_provider_orders_and_joins_with_two_spaces() -> None:
    all_model = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
    fable = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
        display_attention="very_low",
    )

    segment = build_usage_indicator_segment(_badges(fable, all_model))

    assert segment.plain.strip() == "🎭 wk/fable 7% 3d4h  🎭 62% 3d4h"


def test_budget_packing_falls_back_through_the_full_ladder() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    badges = _badges(grok, codex, claude)

    full = build_usage_indicator_segment(badges)
    assert cell_len(full.plain) == full.cell_len

    overflow = build_usage_indicator_segment(badges, budget=full.cell_len - 1)
    assert overflow.cell_len <= full.cell_len - 1
    assert overflow.plain.strip().endswith("+1")
    assert "🛰️" in overflow.plain

    count_only = build_usage_indicator_segment(badges, budget=cell_len(" usage 3"))
    assert count_only.plain.strip() == "usage 3"

    micro = build_usage_indicator_segment(badges, budget=cell_len(" 3"))
    assert micro.plain.strip() == "3"

    assert build_usage_indicator_segment(badges, budget=1).plain == ""
    assert build_usage_indicator_segment(badges, budget=0).plain == ""


def test_open_provider_prefers_first_ranked_badge() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    claude = _entry(provider="claude", remaining_percent=62.0)

    assert usage_indicator_open_provider(_badges(claude, grok)) == "grok"
    assert usage_indicator_open_provider(()) is None


def test_healthy_weekly_window_is_still_open_provider_target() -> None:
    entry = _entry(provider="claude", remaining_percent=62.0)

    badges = _badges(entry)

    assert usage_indicator_open_provider(badges) == "claude"


def test_unknown_provider_falls_back_to_id_marker() -> None:
    entry = _entry(provider="acme", remaining_percent=62.0)

    segment = build_usage_indicator_segment(_badges(entry))

    assert segment.plain.strip() == "ACME 62% 3d4h"


@pytest.mark.parametrize("dark", [True, False])
@pytest.mark.parametrize("decile", range(10))
def test_fresh_percent_and_countdown_share_bold_bucket_color(
    dark: bool, decile: int
) -> None:
    remaining = decile * 10.0 + 5.0
    entry = _entry(provider="claude", remaining_percent=remaining)
    badge = _badges(entry, dark=dark)[0]
    bucket_color = usage_percent_color(remaining, dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    percent_style = _style_for(badge.text, format_usage_percent_text(remaining))
    countdown_style = _style_for(badge.text, "3d4h")

    for style in (percent_style, countdown_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == bucket_color.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()
    assert percent_style.color == countdown_style.color
    assert percent_style.bgcolor == countdown_style.bgcolor


@pytest.mark.parametrize("dark", [True, False])
def test_stale_percent_and_countdown_use_bold_neutral_color(dark: bool) -> None:
    entry = _entry(provider="claude", remaining_percent=62.0, freshness="stale")
    badge = _badges(entry, dark=dark)[0]
    neutral = usage_neutral_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    percent_style = _style_for(badge.text, "62%~")
    countdown_style = _style_for(badge.text, "3d4h")

    for style in (percent_style, countdown_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_passed_reset_percent_and_countdown_use_bold_neutral_color(dark: bool) -> None:
    entry = _entry(
        provider="claude",
        remaining_percent=62.0,
        reset_state="passed",
        seconds_until_reset=0.0,
        resets_at=FROZEN_NOW - 10.0,
    )
    badge = _badges(entry, dark=dark)[0]
    neutral = usage_neutral_color(dark=dark)

    percent_style = _style_for(badge.text, "?%")
    countdown_style = _style_for(badge.text, "0h0m↻")

    for style in (percent_style, countdown_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_fresh_unknown_reset_countdown_matches_percent_bucket_color(dark: bool) -> None:
    entry = _entry(
        provider="claude",
        remaining_percent=62.0,
        reset_state="unknown",
        seconds_until_reset=None,
        resets_at=None,
    )
    badge = _badges(entry, dark=dark)[0]
    bucket_color = usage_percent_color(62.0, dark=dark)

    percent_style = _style_for(badge.text, "62%")
    countdown_style = _style_for(badge.text, "?")

    for style in (percent_style, countdown_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == bucket_color.lower()


@pytest.mark.parametrize(
    ("remaining", "expected_text"),
    [(0.0, "0%"), (0.4, "<1%"), (100.0, "100%")],
)
@pytest.mark.parametrize("dark", [True, False])
def test_percent_text_edge_values_share_color_with_countdown(
    dark: bool, remaining: float, expected_text: str
) -> None:
    entry = _entry(provider="claude", remaining_percent=remaining)
    badge = _badges(entry, dark=dark)[0]
    bucket_color = usage_percent_color(remaining, dark=dark)

    percent_style = _style_for(badge.text, expected_text)
    countdown_style = _style_for(badge.text, "3d4h")

    assert percent_style.color is not None
    assert percent_style.color.get_truecolor().hex == bucket_color.lower()
    assert percent_style == countdown_style


@pytest.mark.parametrize("dark", [True, False])
def test_specifier_and_separators_use_normal_weight_neutral_on_badge_surface(
    dark: bool,
) -> None:
    entry = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        window_label="Claude weekly Fable",
        weekly_all=False,
        period_kind="weekly",
        duration_seconds=None,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
    )
    badge = _badges(entry, dark=dark)[0]
    neutral = usage_neutral_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    specifier_style = _style_for(badge.text, "wk/fable")
    icon_style = _style_for(badge.text, "🎭 ")

    for style in (specifier_style, icon_style):
        assert not style.bold
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_warning_and_rejected_markers_render_bold_on_badge_surface(dark: bool) -> None:
    warning_entry = _entry(
        provider="codex", remaining_percent=50.0, collector_problem=True
    )
    rejected_entry = _entry(
        provider="grok",
        remaining_percent=4.0,
        vendor_state="rejected",
        display_attention="rejected",
    )
    warning_badge = _badges(warning_entry, dark=dark)[0]
    rejected_badge = _badges(rejected_entry, dark=dark)[0]
    badge_surface = _usage_badge_surface_color(dark=dark)

    base_style = Style.parse(f"not bold not dim not reverse on {badge_surface}")
    warning_style = _style_for(warning_badge.text, "⚠")
    rejected_style = _style_for(rejected_badge.text, "!")

    assert warning_style == Style.combine(
        [base_style, Style.parse(usage_warning_style(dark=dark))]
    )
    assert rejected_style == Style.combine(
        [base_style, Style.parse(usage_rejected_style(dark=dark))]
    )


@pytest.mark.parametrize("dark", [True, False])
def test_badge_gaps_use_the_app_background_not_the_badge_surface(dark: bool) -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    claude = _entry(provider="claude", remaining_percent=62.0)
    segment = build_usage_indicator_segment(_badges(grok, claude, dark=dark), dark=dark)
    gap_surface = _usage_gap_surface_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    segments = _rendered_segments(segment)
    # The leading run (before the first badge) and any exact two-space run
    # (between badges) are gaps; single-space runs elsewhere are a badge's
    # own internal separators, painted on the badge surface instead.
    gap_runs = [segments[0][1]] + [
        style for text, style in segments[1:] if text == "  "
    ]
    assert gap_runs, "expected at least one blank gap run"
    for gap_style in gap_runs:
        assert gap_style is not None
        assert gap_style.bgcolor is not None
        assert gap_style.bgcolor.get_truecolor().hex == gap_surface.lower()
        assert gap_style.bgcolor.get_truecolor().hex != badge_surface.lower()


@pytest.mark.parametrize("dark", [True, False])
def test_overflow_and_fallback_disclosure_render_bold_neutral_on_badge_surface(
    dark: bool,
) -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    badges = _badges(grok, codex, claude, dark=dark)
    full = build_usage_indicator_segment(badges, dark=dark)
    neutral = usage_neutral_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    overflow = build_usage_indicator_segment(
        badges, budget=full.cell_len - 1, dark=dark
    )
    plus_one_style = _style_for(overflow, "+1")

    count_only = build_usage_indicator_segment(
        badges, budget=cell_len(" usage 3"), dark=dark
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
        colors.append(usage_warning_style(dark=dark).rsplit(" ", 1)[-1])
        colors.append(usage_rejected_style(dark=dark).rsplit(" ", 1)[-1])
        for color in colors:
            assert _contrast_ratio(color, badge_surface) >= 4.5, (dark, color)
