"""Tests for the ``llm.usage`` doctor check."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor.checks_providers import _check_llm_usage
from sase.doctor.runner import DoctorContext
from sase.llm_provider.usage.config import UsageMetricsSettings
from sase.llm_provider.usage.store import (
    ProviderUsageStateError,
    ProviderUsageStoreDiagnostic,
    ProviderUsageStoreRead,
)


def _context(tmp_path: Path, env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env=env or {},
    )


def _usage_store_read(
    *providers: dict[str, object],
    diagnostics: tuple[ProviderUsageStoreDiagnostic, ...] = (),
) -> ProviderUsageStoreRead:
    return ProviderUsageStoreRead(
        version=1,
        snapshot={
            "attention": None,
            "collection_health": "ok" if providers else "empty",
            "generated_at": 1_800_000_000.0,
            "providers": list(providers),
            "schema_version": 1,
        },
        diagnostics=diagnostics,
    )


def _usage_provider(
    status: str,
    *,
    collector_health: dict[str, object] | None = None,
    diagnostic: str | None = None,
) -> dict[str, object]:
    return {
        "collection_status": status,
        "collector_health": collector_health,
        "diagnostic": diagnostic
        if diagnostic is not None
        else "provider is logged out"
        if status == "unauthenticated"
        else None,
        "provider": "codex",
        "summary": {"freshness": "fresh"},
        "windows": [],
    }


def _patch_usage_check_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_usage_metrics_settings",
        lambda: UsageMetricsSettings(),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.provider_usage_state_path",
        lambda: tmp_path / "llm_provider_usage.json",
    )


def test_llm_usage_skips_when_config_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_usage_metrics_settings",
        lambda: UsageMetricsSettings(enabled=False),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.provider_usage_state_path",
        lambda: tmp_path / "llm_provider_usage.json",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.load_provider_usage",
        lambda **kwargs: pytest.fail("disabled usage diagnostics must not read store"),
    )

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "SKIP"
    assert "usage_metrics" in check.summary


def test_llm_usage_warns_when_cache_is_empty(monkeypatch, tmp_path) -> None:
    _patch_usage_check_defaults(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.eligible_usage_providers",
        lambda: ("codex",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.load_provider_usage",
        lambda **kwargs: _usage_store_read(),
    )

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "WARN"
    assert "No subscription usage observations" in check.summary
    assert check.next_steps == ("Run `sase usage refresh`.",)
    assert check.data["eligible_providers"] == ("codex",)


def test_llm_usage_errors_when_cache_is_unreadable(monkeypatch, tmp_path) -> None:
    _patch_usage_check_defaults(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.eligible_usage_providers",
        lambda: (),
    )

    def fail_read(**kwargs: object) -> ProviderUsageStoreRead:
        raise ProviderUsageStateError("bad cache")

    monkeypatch.setattr("sase.doctor.checks_providers.load_provider_usage", fail_read)

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "ERROR"
    assert "could not be read" in check.summary
    assert "bad cache" in check.details


def test_llm_usage_warns_for_provider_collection_problems(
    monkeypatch, tmp_path
) -> None:
    _patch_usage_check_defaults(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.eligible_usage_providers",
        lambda: ("codex",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.load_provider_usage",
        lambda **kwargs: _usage_store_read(
            _usage_provider("unauthenticated"),
            diagnostics=(
                ProviderUsageStoreDiagnostic(
                    provider="codex",
                    message="cached diagnostic",
                ),
            ),
        ),
    )

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "WARN"
    assert "collection problems" in check.summary
    assert any("codex: unauthenticated" in detail for detail in check.details)


def test_llm_usage_warns_for_failing_collector_health(monkeypatch, tmp_path) -> None:
    _patch_usage_check_defaults(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.eligible_usage_providers",
        lambda: ("codex",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.time.time",
        lambda: 1_800_000_000.0,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.load_provider_usage",
        lambda **kwargs: _usage_store_read(
            _usage_provider(
                "ok",
                collector_health={
                    "state": "failing",
                    "consecutive_failures": 5,
                    "last_success_at": 1_799_740_800.0,
                    "failing_since": 1_799_740_800.0,
                },
                diagnostic="provider CLI request shape changed",
            )
        ),
    )

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "WARN"
    assert "collection problems" in check.summary
    assert check.data["collector_health_counts"]["failing"] == 1
    assert any(
        "codex: collector failing (5 consecutive failures, last success 3d ago)"
        in detail
        for detail in check.details
    )


def test_llm_usage_reports_degraded_collector_health_as_detail_only(
    monkeypatch, tmp_path
) -> None:
    _patch_usage_check_defaults(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.eligible_usage_providers",
        lambda: ("codex",),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.time.time",
        lambda: 1_800_000_000.0,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.load_provider_usage",
        lambda **kwargs: _usage_store_read(
            _usage_provider(
                "ok",
                collector_health={
                    "state": "degraded",
                    "consecutive_failures": 2,
                    "last_success_at": 1_799_996_400.0,
                    "failing_since": 1_799_996_400.0,
                },
                diagnostic="one retry failed",
            )
        ),
    )

    check = _check_llm_usage(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["collector_health_counts"]["degraded"] == 1
    assert any(
        "codex: collector degraded (2 consecutive failures, last success 1h ago)"
        in detail
        for detail in check.details
    )
