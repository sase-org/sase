"""Cached subscription-usage snapshot loading for the ACE Providers home."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel_usage_state as usage_state
from sase.llm_provider.usage.config import UsageMetricsSettings
from sase.llm_provider.usage.store import (
    ProviderUsageStoreDiagnostic,
    ProviderUsageStoreRead,
)
from tests._usage_view_helpers import usage_provider


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        usage_state, "get_usage_metrics_settings", lambda: UsageMetricsSettings()
    )


def test_load_usage_view_snapshot_reads_cached_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)
    provider = usage_provider("codex")
    read = ProviderUsageStoreRead(
        version=1,
        snapshot={"providers": [provider], "generated_at": 1.0},
        diagnostics=(ProviderUsageStoreDiagnostic(provider=None, message="stale"),),
    )
    monkeypatch.setattr(usage_state, "load_provider_usage", lambda **_kw: read)

    snapshot = usage_state.load_usage_view_snapshot(now=100.0)

    assert snapshot.providers == (provider,)
    assert snapshot.diagnostics == read.diagnostics
    assert snapshot.captured_at == 100.0
    assert snapshot.load_error is None


def test_load_usage_view_snapshot_ignores_malformed_provider_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)
    read = ProviderUsageStoreRead(
        version=1,
        snapshot={"providers": ["not-a-mapping", usage_provider("grok")]},
        diagnostics=(),
    )
    monkeypatch.setattr(usage_state, "load_provider_usage", lambda **_kw: read)

    snapshot = usage_state.load_usage_view_snapshot(now=1.0)

    assert [p["provider"] for p in snapshot.providers] == ["grok"]


def test_load_usage_view_snapshot_reports_store_errors_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch)

    def _raise(**_kw: object) -> ProviderUsageStoreRead:
        raise RuntimeError("store locked")

    monkeypatch.setattr(usage_state, "load_provider_usage", _raise)

    snapshot = usage_state.load_usage_view_snapshot(now=1.0)

    assert snapshot.providers == ()
    assert snapshot.load_error == "store locked"
