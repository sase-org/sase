"""Tests for ``llm_provider.usage_metrics`` parsing and the beta flag gate."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.llm_provider.usage.config import (
    collection_skip_reason,
    get_usage_metrics_settings,
)
from sase.llm_provider.usage.probe import (
    default_probe_context,
    record_passive_usage_observation,
    run_usage_probe,
    worker_environ,
)
from sase.llm_provider.usage.synthetic import (
    SECRET_CANARY,
    SYNTHETIC_PLUGIN_SPEC,
    _SyntheticUsageProvider,
)
from sase.llm_provider.usage.types import observation_schema_version
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


def test_flag_off_skips_probes_and_passive_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    context = default_probe_context("synth", now=1_800_000_000.0)
    with override_flags(provider_usage_metrics=False):
        assert current_flags().enabled(FeatureFlag.provider_usage_metrics) is False
        assert collection_skip_reason("synth") == "flag_disabled"
        result = run_usage_probe(
            context,
            isolate=False,
            plugin=_SyntheticUsageProvider(),
            now=1_800_000_000.0,
        )
        assert result.skipped == "flag_disabled"
        assert result.observation is None
        assert (
            record_passive_usage_observation({"provider": "synth"}, now=1_800_000_000.0)
            is None
        )


def test_config_disabled_skips_when_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": False}})
    with override_flags(provider_usage_metrics=True):
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
    with override_flags(provider_usage_metrics=True):
        assert collection_skip_reason("fourth") == "provider_disabled"
        assert collection_skip_reason("synth") is None


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
    with override_flags(provider_usage_metrics=True):
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
