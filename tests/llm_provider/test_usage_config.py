"""Tests for ``llm_provider.usage_metrics`` parsing and collection gating."""

from __future__ import annotations

import pytest

from sase.llm_provider.usage import config as usage_config
from sase.llm_provider.usage.config import (
    collection_skip_reason,
    get_usage_indicator_settings,
    get_usage_metrics_settings,
)
from sase.llm_provider.usage.probe import (
    default_probe_context,
    record_passive_usage_observation,
    run_usage_probe,
    worker_environ,
)
from sase.testing.usage_synthetic import (
    SECRET_CANARY,
    SYNTHETIC_PLUGIN_SPEC,
    _SyntheticUsageProvider,
)
from sase.llm_provider.usage.types import (
    observation_schema_version,
    validated_status_observation,
)
from tests._rust_extension_module_helpers import install_fake_rust_extension
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_usage_metrics_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(monkeypatch, {})
    settings = get_usage_metrics_settings()
    assert settings.enabled is True
    assert settings.refresh_seconds == 300.0
    assert settings.warn_percent == 75.0
    assert settings.critical_percent == 90.0
    assert settings.provider_enabled("claude") is True
    assert settings.provider_enabled("fourth") is True


def test_usage_metrics_parses_per_provider_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "usage_metrics": {
                "enabled": True,
                "refresh_seconds": 120,
                "warn_percent": 70,
                "critical_percent": 85,
                "providers": {"synth": {"enabled": False}, "other": "ignored"},
            }
        },
    )
    settings = get_usage_metrics_settings()
    assert settings.refresh_seconds == 120.0
    assert settings.warn_percent == 70.0
    assert settings.critical_percent == 85.0
    assert settings.provider_enabled("synth") is False
    assert settings.provider_enabled("claude") is True


def test_usage_indicator_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def provider_usage_validate_indicator_config(
        indicator: object | None = None,
    ) -> dict[str, object]:
        calls.append(indicator)
        return {
            "schema_version": 1,
            "config": {
                "enabled": True,
                "default": {
                    "kind": "below_remaining_percent",
                    "below_remaining_percent": 20.0,
                },
                "weekly_all": {"kind": "always"},
                "providers": {
                    "claude": {
                        "default": None,
                        "windows": {"session": {"kind": "always"}},
                    }
                },
            },
            "diagnostics": [],
        }

    install_fake_rust_extension(
        monkeypatch,
        provider_usage_validate_indicator_config=provider_usage_validate_indicator_config,
    )
    monkeypatch.setattr(
        usage_config, "current_config_token", lambda: ("config", "indicator-defaults")
    )
    monkeypatch.setattr(usage_config, "_indicator_settings_cache", None)
    monkeypatch.setattr(usage_config, "_indicator_diagnostics_token", None)
    mock_provider_config(
        monkeypatch,
        {
            "usage_metrics": {
                "indicator": {
                    "providers": {
                        "claude": {"windows": {"session": "always"}},
                    }
                }
            }
        },
    )

    settings = get_usage_indicator_settings()

    assert settings.enabled is True
    assert settings.raw == {"providers": {"claude": {"windows": {"session": "always"}}}}
    assert settings.config["providers"]["claude"]["windows"]["session"] == {
        "kind": "always"
    }
    assert calls == [settings.raw]


def test_usage_indicator_settings_are_cached_by_config_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = ("config", 1)
    calls = 0

    def current_config_token() -> tuple[str, int]:
        return token

    def provider_usage_validate_indicator_config(
        indicator: object | None = None,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "schema_version": 1,
            "config": {
                "enabled": False,
                "default": {"kind": "never"},
                "weekly_all": {"kind": "always"},
                "providers": {},
            },
            "diagnostics": [
                {"path": "indicator.default", "message": "override was ignored"}
            ],
        }

    install_fake_rust_extension(
        monkeypatch,
        provider_usage_validate_indicator_config=provider_usage_validate_indicator_config,
    )
    monkeypatch.setattr(usage_config, "current_config_token", current_config_token)
    monkeypatch.setattr(usage_config, "_indicator_settings_cache", None)
    monkeypatch.setattr(usage_config, "_indicator_diagnostics_token", None)
    mock_provider_config(monkeypatch, {"usage_metrics": {"indicator": "bad"}})

    first = get_usage_indicator_settings()
    second = get_usage_indicator_settings()

    assert first is second
    assert calls == 1
    assert first.enabled is False
    assert first.diagnostics[0].path == "indicator.default"


def test_invalid_thresholds_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "usage_metrics": {
                "refresh_seconds": 10,
                "warn_percent": 90,
                "critical_percent": 10,
            }
        },
    )
    settings = get_usage_metrics_settings()
    assert settings.refresh_seconds == 300.0
    assert settings.warn_percent == 75.0
    assert settings.critical_percent == 90.0


def test_config_disabled_skips_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": False}})
    assert collection_skip_reason("synth") == "config_disabled"
    result = run_usage_probe(
        default_probe_context("synth", now=1_800_000_000.0),
        isolate=False,
        plugin=_SyntheticUsageProvider(),
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        now=1_800_000_000.0,
    )
    assert result.skipped == "config_disabled"


def test_per_provider_disable_does_not_hard_code_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    mock_provider_config(
        monkeypatch,
        {"usage_metrics": {"providers": {"fourth": {"enabled": False}}}},
    )
    assert collection_skip_reason("fourth") == "provider_disabled"
    assert collection_skip_reason("synth") is None


def test_vendor_drift_status_observation_uses_default_diagnostic() -> None:
    now = 1_800_000_000.0
    observation = validated_status_observation(
        default_probe_context("synth", now=now),
        now=now,
        outcome="error",
        reason_code="vendor_drift",
    )
    assert observation["reason_code"] == "vendor_drift"
    assert observation["diagnostic"] == "provider CLI request shape changed"


def test_passive_observation_validates_when_collection_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    now = 1_800_000_000.0
    observation = {
        "schema_version": observation_schema_version(),
        "provider": "synth",
        "context_id": "ctx",
        "account_generation": 1,
        "ordering_token": now - 10,
        "received_at": now - 5,
        "source": "stream_event",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": None,
        "completeness": "complete",
        "account_mode": "subscription",
        "plan": None,
        "windows": [
            {
                "key": "week",
                "label": "Weekly",
                "used_percent": 20.0,
                "resets_at": now + 3600,
                "duration_seconds": None,
                "period_start": None,
                "applicability": {"kind": "account"},
                "observed_at": now - 10,
                "source": "stream_event",
                "vendor_state": "allowed",
            }
        ],
    }
    validated = record_passive_usage_observation(observation, now=now)
    assert validated is not None
    assert validated["source"] == "stream_event"
    assert validated["windows"][0]["key"] == "week"


def test_worker_environ_strips_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET_CANARY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("SASE_GROK_PATH", "/opt/grok")
    env = worker_environ()
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert SECRET_CANARY not in env.values()
    assert env.get("SASE_GROK_PATH") == "/opt/grok"
