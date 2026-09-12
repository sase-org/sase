"""Compact provider-usage header text, grouping, and tooltip tests.

Color, style, and contrast coverage lives in
``test_provider_usage_indicator_presentation_style.py``. Budget packing,
overflow, and projection integration live in
``test_provider_usage_indicator_presentation_layout.py``.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
    usage_indicator_open_provider,
    usage_indicator_tooltip_lines,
)
from sase.ace.tui.widgets._usage_indicator_format import format_usage_percent_text
from tests._provider_usage_indicator_presentation_helpers import (
    FROZEN_NOW,
    _entry,
    _groups,
    _scope,
)


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


def test_grouped_default_first_text_order_icons_gaps_and_dots() -> None:
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

    assert segment.plain == (" 🎭 62% 3d4h · fable 7% 1d8h · 5h 18% 2h9m  🤖 81% 5d2h ")
    assert segment.plain.count("🎭") == 1
    assert segment.plain.count("🤖") == 1
    assert segment.plain.count("·") == 2
    assert "  🤖" in segment.plain
    assert "(" not in segment.plain
    assert ")" not in segment.plain
    assert "|" not in segment.plain
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
    assert "·" not in segment.plain
    assert "|" not in segment.plain


def test_multiple_default_classified_entries_keep_lowest_key_unnamed() -> None:
    later = _entry(window_key="weekly:b", remaining_percent=55.0)
    anchor = _entry(window_key="weekly:a", remaining_percent=62.0)

    segment = build_usage_indicator_segment(_groups(later, anchor))

    assert segment.plain == " 🎭 62% 3d4h · wk/all 55% 3d4h "


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


def test_open_provider_prefers_first_ranked_group() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    claude = _entry(provider="claude", remaining_percent=62.0)

    assert usage_indicator_open_provider(_groups(claude, grok)) == "grok"
    assert usage_indicator_open_provider(()) is None


def test_unknown_provider_falls_back_to_id_marker() -> None:
    entry = _entry(provider="acme", remaining_percent=62.0)

    segment = build_usage_indicator_segment(_groups(entry))

    assert segment.plain.strip() == "ACME 62% 3d4h"
