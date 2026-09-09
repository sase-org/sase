"""Cached subscription-usage presentation helpers."""

from __future__ import annotations

import io

from rich.console import Console

from sase.llm_provider.usage import presentation
from sase.llm_provider.usage.presentation import (
    render_usage_plain,
    render_usage_rich,
    reset_label,
    timestamp_label,
    usage_snapshot_json_payload,
)
from sase.llm_provider.usage.store import ProviderUsageStoreDiagnostic


def _snapshot(*providers: dict[str, object]) -> dict[str, object]:
    return {
        "attention": None,
        "collection_health": "ok" if providers else "empty",
        "generated_at": 1_800_000_000.0,
        "providers": list(providers),
        "schema_version": 1,
    }


def _codex_provider() -> dict[str, object]:
    return {
        "account_generation": 1,
        "account_mode": "chatgpt",
        "attention": {"kind": "low", "provider": "codex", "window_key": "shared"},
        "collection_reason": None,
        "collection_status": "ok",
        "completeness": "complete",
        "context_ref": "codex:default:1",
        "diagnostic": None,
        "known_constraints": [],
        "last_attempt_at": 1_800_000_000.0,
        "last_full_observation_at": 1_800_000_000.0,
        "plan": "Plus",
        "provider": "codex",
        "summary": {
            "completeness": "complete",
            "freshness": "fresh",
            "limiting_window_keys": ["shared"],
            "remaining_percent": 12.5,
            "scope": {"kind": "models", "model_ids": ["gpt-5"]},
            "used_percent": 87.5,
        },
        "windows": [
            {
                "age_seconds": 30.0,
                "applicability": {"kind": "models", "model_ids": ["gpt-5"]},
                "duration_seconds": 18_000.0,
                "exceeded_by_percent": None,
                "freshness": "fresh",
                "key": "shared",
                "label": "Shared 5h",
                "observed_at": 1_799_999_970.0,
                "period_start": 1_799_982_000.0,
                "remaining_percent": 12.5,
                "reset_passed": False,
                "resets_at": 1_800_007_200.0,
                "source": "probe",
                "used_percent": 87.5,
                "vendor_state": "warning",
            }
        ],
    }


def _failing_codex_provider() -> dict[str, object]:
    provider = _codex_provider()
    provider["collection_reason"] = "vendor_drift"
    provider["diagnostic"] = "primary request shape was rejected"
    provider["collector_health"] = {
        "state": "failing",
        "consecutive_failures": 5,
        "last_success_at": 1_799_740_800.0,
        "failing_since": 1_799_740_800.0,
    }
    return provider


def test_plain_empty_snapshot_points_at_refresh() -> None:
    text = render_usage_plain(_snapshot())

    assert text == "Subscription usage\nNo observations yet; run sase usage refresh."


def test_plain_window_records_include_core_remaining_text(monkeypatch) -> None:
    monkeypatch.setattr(
        presentation,
        "provider_usage_format_remaining_text",
        lambda used: f"{100.0 - used:g}% left",
    )

    text = render_usage_plain(
        _snapshot(_codex_provider()),
        [ProviderUsageStoreDiagnostic(provider="codex", message="cache warning")],
        verbose=True,
        now=1_800_000_000.0,
    )

    assert 'provider=codex status=ok remaining="12.5% left"' in text
    assert 'window provider=codex key=shared label="Shared 5h"' in text
    assert 'reset="in 2h"' in text
    assert "scope=models:gpt-5" in text
    assert 'diagnostic provider=codex message="cache warning"' in text


def test_collector_health_helpers_render_compact_unhealthy_state() -> None:
    health = {
        "state": "failing",
        "consecutive_failures": 5,
        "last_success_at": 1_799_740_800.0,
        "failing_since": 1_799_740_800.0,
    }

    assert presentation._collector_health_label(health, reason="vendor_drift") == (
        "failing · vendor drift · 5x"
    )
    assert presentation._collector_health_style(health) == "bold #FFAF5F"


def test_rich_status_cell_uses_unhealthy_collector_health() -> None:
    stream = io.StringIO()
    console = Console(
        file=stream,
        force_terminal=False,
        color_system=None,
        width=120,
    )

    console.print(
        render_usage_rich(_snapshot(_failing_codex_provider()), now=1_800_000_000.0)
    )

    text = stream.getvalue()
    assert "failing" in text
    assert "vendor drift" in text
    assert "5x" in text


def test_verbose_plain_provider_record_includes_collector_health() -> None:
    text = render_usage_plain(
        _snapshot(_failing_codex_provider()),
        verbose=True,
        now=1_800_000_000.0,
    )

    assert "health=failing" in text
    assert "consecutive_failures=5" in text
    assert 'last_success="2027-01-12 03:00:00 EST (3d ago)"' in text
    assert 'failing_since="2027-01-12 03:00:00 EST (3d ago)"' in text


def test_json_payload_filters_and_reports_missing_requested_providers() -> None:
    payload = usage_snapshot_json_payload(
        _snapshot(_codex_provider()),
        requested_providers=("codex", "grok"),
    )

    assert [item["provider"] for item in payload["providers"]] == ["codex"]
    assert payload["requested_providers"] == ["codex", "grok"]
    assert payload["missing_providers"] == ["grok"]


def test_json_payload_filter_preserves_collector_health() -> None:
    provider = _failing_codex_provider()

    payload = usage_snapshot_json_payload(
        _snapshot(provider),
        requested_providers=("codex",),
    )

    assert payload["providers"][0]["collector_health"] == provider["collector_health"]


def test_verbose_reset_label_omits_relative_age_for_a_future_timestamp() -> None:
    now = 1_800_000_000.0
    label = reset_label(
        {"resets_at": now + 3_600.0, "reset_passed": False},
        now,
        verbose=True,
    )

    assert label == "in 1h (2027-01-15 04:00:00 EST)"
    assert "ago" not in label


def test_past_observed_at_timestamp_keeps_relative_age_suffix() -> None:
    now = 1_800_000_000.0
    observed_at = 1_799_999_970.0

    assert timestamp_label(observed_at, now) == "2027-01-15 02:59:30 EST (30s ago)"

    text = render_usage_plain(_snapshot(_codex_provider()), verbose=True, now=now)

    assert 'observed_at="2027-01-15 02:59:30 EST (30s ago)"' in text
    assert 'resets_at="2027-01-15 05:00:00 EST"' in text
    assert "05:00:00 EST (0s ago)" not in text
