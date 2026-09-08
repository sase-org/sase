"""Pure Rich rendering helpers for the ACE Providers · Usage view."""

from __future__ import annotations

from sase.ace.tui.modals.models_panel_usage_rendering import (
    _provider_attention_style,
    _usage_meter,
    detail_columns_for_width,
    provider_detail_header,
    provider_summary_text,
    usage_view_width_tier,
    window_detail_row,
)
from tests._usage_view_helpers import FROZEN_NOW, usage_provider, usage_window


def test_usage_meter_full_and_empty_and_unknown() -> None:
    assert _usage_meter(100.0) == "█" * 10
    assert _usage_meter(0.0) == "░" * 10
    assert _usage_meter(None) == "?" * 10


def test_usage_meter_partial_rounds_to_nearest_block() -> None:
    meter = _usage_meter(67.0)
    assert meter.count("█") == 7
    assert meter.count("░") == 3


def test_provider_summary_text_shows_meter_and_scope() -> None:
    provider = usage_provider("codex", used_percent=87.5, remaining_percent=12.5)
    text = provider_summary_text(provider).plain

    assert "CODEX" in text
    assert "12.5% left" in text or "%" in text
    assert "models:gpt-5" in text


def test_provider_summary_text_marks_updating() -> None:
    provider = usage_provider("codex")
    assert "Updating" in provider_summary_text(provider, updating=True).plain
    assert "Updating" not in provider_summary_text(provider, updating=False).plain


def test_provider_summary_text_falls_back_to_status_without_summary() -> None:
    provider = usage_provider(
        "grok",
        used_percent=None,
        remaining_percent=None,
        collection_status="unauthenticated",
    )
    text = provider_summary_text(provider).plain
    assert "logged out" in text


def test_provider_attention_style_prefers_rejected_over_low() -> None:
    rejected = usage_provider("codex", attention={"kind": "rejected"})
    low = usage_provider("codex", attention={"kind": "low"})
    healthy = usage_provider("codex", attention=None)

    assert _provider_attention_style(rejected) == "bold red"
    assert _provider_attention_style(low) == "yellow"
    assert _provider_attention_style(healthy) == ""


def test_provider_detail_header_includes_plan_mode_and_diagnostic() -> None:
    provider = usage_provider(
        "codex", plan="Plus", account_mode="chatgpt", diagnostic="cache warning"
    )
    text = provider_detail_header(provider, now=FROZEN_NOW).plain

    assert "Plan: Plus" in text
    assert "Mode: chatgpt" in text
    assert "cache warning" in text


def test_window_detail_row_reports_remaining_and_reset() -> None:
    window = usage_window(used_percent=87.5, resets_at=FROZEN_NOW + 7_200.0)
    row = window_detail_row(window, now=FROZEN_NOW)

    assert row[0] == "Shared 5h"
    assert "%" in row[1] or "left" in row[1]
    assert row[3].startswith("in ")


def test_window_detail_row_reports_exceeded() -> None:
    window = usage_window(used_percent=105.0, exceeded_by_percent=5.0)
    row = window_detail_row(window, now=FROZEN_NOW)

    assert "exceeded by 5" in row[1]


def test_window_detail_row_reset_passed_never_negative() -> None:
    window = usage_window(reset_passed=True, resets_at=FROZEN_NOW - 10.0)
    row = window_detail_row(window, now=FROZEN_NOW)

    assert row[3] == "reset passed"


def test_usage_view_width_tier_breakpoints() -> None:
    assert usage_view_width_tier(120) == "wide"
    assert usage_view_width_tier(119) == "medium"
    assert usage_view_width_tier(80) == "medium"
    assert usage_view_width_tier(79) == "narrow"
    assert usage_view_width_tier(60) == "narrow"


def test_provider_summary_text_drops_meter_below_wide_tier() -> None:
    provider = usage_provider("codex", used_percent=87.5, remaining_percent=12.5)

    wide = provider_summary_text(provider, width=120).plain
    medium = provider_summary_text(provider, width=80).plain

    assert "█" in wide or "░" in wide
    assert "█" not in medium and "░" not in medium
    assert "left" in medium or "%" in medium


def test_detail_columns_for_width_stacks_at_narrow_tier() -> None:
    wide_columns = detail_columns_for_width(120)
    narrow_columns = detail_columns_for_width(60)

    assert "Source" in wide_columns
    assert len(narrow_columns) < len(wide_columns)
    assert "Source" not in narrow_columns


def test_window_detail_row_matches_column_count_at_every_tier() -> None:
    window = usage_window()
    for width in (120, 80, 60):
        row = window_detail_row(window, now=FROZEN_NOW, width=width)
        assert len(row) == len(detail_columns_for_width(width))


def test_window_detail_row_stacks_scope_reset_age_at_narrow_tier() -> None:
    window = usage_window()
    row = window_detail_row(window, now=FROZEN_NOW, width=60)

    combined = row[2]
    assert "models:gpt-5" in combined
    assert "in " in combined
