"""Compact provider-usage top-bar presentation tests."""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_badges,
    usage_indicator_open_provider,
    usage_indicator_tooltip_lines,
)
from sase.ace.tui.widgets._usage_indicator_palette import usage_percent_color

FROZEN_NOW = 1_800_000_000.0


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
