"""Cached subscription-usage presentation helpers."""

from __future__ import annotations

from sase.llm_provider.usage import presentation
from sase.llm_provider.usage.presentation import (
    render_usage_plain,
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


def test_json_payload_filters_and_reports_missing_requested_providers() -> None:
    payload = usage_snapshot_json_payload(
        _snapshot(_codex_provider()),
        requested_providers=("codex", "grok"),
    )

    assert [item["provider"] for item in payload["providers"]] == ["codex"]
    assert payload["requested_providers"] == ["codex", "grok"]
    assert payload["missing_providers"] == ["grok"]
