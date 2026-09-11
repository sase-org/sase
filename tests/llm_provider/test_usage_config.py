"""Tests for ``llm_provider.usage_metrics`` parsing and collection gating."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import yaml

from sase.config import core as config_core
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
from sase.llm_provider.usage.store import provider_usage_project_indicator
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
from tests._usage_view_helpers import FROZEN_NOW, usage_provider, usage_window
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _clear_usage_indicator_cache() -> None:
    usage_config._indicator_settings_cache = None
    usage_config._indicator_diagnostics_token = None


def _write_user_config(config: Mapping[str, Any]) -> None:
    config_core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (config_core.CONFIG_DIR / "sase.yml").write_text(
        yaml.safe_dump(dict(config)),
        encoding="utf-8",
    )
    config_core.clear_config_cache()
    _clear_usage_indicator_cache()


def _claude_indicator_snapshot(
    *,
    include_fable: bool = True,
    fable_remaining: float = 100.0,
) -> dict[str, Any]:
    windows = [
        _weekly_window(
            key="weekly",
            label="Week",
            remaining_percent=90.0,
            resets_at=FROZEN_NOW + 604_800.0,
            applicability={"kind": "account"},
        ),
        _usage_window(
            key="session-low",
            label="Claude five-hour session",
            remaining_percent=19.99,
            resets_at=FROZEN_NOW + 18_000.0,
            applicability={"kind": "account"},
            duration_seconds=18_000.0,
        ),
        _usage_window(
            key="session-boundary",
            label="Claude boundary session",
            remaining_percent=20.0,
            resets_at=FROZEN_NOW + 18_000.0,
            applicability={"kind": "account"},
            duration_seconds=18_000.0,
        ),
    ]
    if include_fable:
        windows.append(
            _weekly_window(
                key="weekly:claude-fable-5",
                label="Claude weekly Fable",
                remaining_percent=fable_remaining,
                resets_at=FROZEN_NOW + 604_800.0,
                applicability={
                    "kind": "models",
                    "model_ids": ["claude-fable-5"],
                },
            )
        )
    return {
        "schema_version": 1,
        "generated_at": FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "claude",
                used_percent=10.0,
                remaining_percent=90.0,
                attention={
                    "kind": "none",
                    "provider": "claude",
                    "window_key": "weekly",
                },
                windows=windows,
                known_constraints=[],
            )
        ],
        "attention": None,
    }


def _weekly_window(
    *,
    key: str,
    label: str,
    remaining_percent: float,
    resets_at: float,
    applicability: Mapping[str, Any],
) -> dict[str, Any]:
    return _usage_window(
        key=key,
        label=label,
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability=applicability,
        duration_seconds=604_800.0,
    )


def _usage_window(
    *,
    key: str,
    label: str,
    remaining_percent: float,
    resets_at: float,
    applicability: Mapping[str, Any],
    duration_seconds: float,
) -> dict[str, Any]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=max(0.0, 100.0 - remaining_percent),
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability=applicability,
    )
    window["duration_seconds"] = duration_seconds
    return window


def _projected_window_keys(
    snapshot: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    settings = get_usage_indicator_settings()
    projection = provider_usage_project_indicator(
        snapshot or _claude_indicator_snapshot(),
        indicator=settings.raw,
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    return tuple(str(entry["window_key"]) for entry in projection.entries)


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
    _clear_usage_indicator_cache()
    settings = get_usage_indicator_settings()

    assert settings.enabled is True
    assert settings.raw is not None
    assert settings.config["providers"]["claude"]["windows"][
        "weekly:claude-fable-5"
    ] == {"kind": "always"}
    assert _projected_window_keys() == (
        "session-low",
        "weekly",
        "weekly:claude-fable-5",
    )

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
    monkeypatch.setattr(
        usage_config, "current_config_token", lambda: ("config", "indicator-override")
    )
    _clear_usage_indicator_cache()

    settings = get_usage_indicator_settings()

    assert settings.enabled is True
    assert settings.raw == {"providers": {"claude": {"windows": {"session": "always"}}}}
    assert settings.config["providers"]["claude"]["windows"]["session"] == {
        "kind": "always"
    }


@pytest.mark.parametrize(
    ("user_config", "expected"),
    [
        pytest.param(
            {"llm_provider": {"usage_metrics": {"indicator": {"providers": {}}}}},
            ("session-low", "weekly", "weekly:claude-fable-5"),
            id="empty-provider-map-keeps-bundled-exact-window",
        ),
        pytest.param(
            {
                "llm_provider": {
                    "usage_metrics": {
                        "indicator": {
                            "providers": {
                                "claude": {
                                    "windows": {"weekly:claude-fable-5": "never"}
                                }
                            }
                        }
                    }
                }
            },
            ("session-low", "weekly"),
            id="exact-key-never-wins",
        ),
        pytest.param(
            {
                "llm_provider": {
                    "usage_metrics": {
                        "indicator": {
                            "providers": {
                                "claude": {
                                    "windows": {
                                        "weekly:claude-fable-5": {
                                            "below_remaining_percent": 20
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            ("session-low", "weekly"),
            id="exact-key-threshold-restores-generic-boundary",
        ),
        pytest.param(
            {
                "llm_provider": {
                    "usage_metrics": {
                        "indicator": {"providers": {"codex": {"default": "always"}}}
                    }
                }
            },
            ("session-low", "weekly", "weekly:claude-fable-5"),
            id="unrelated-provider-override-keeps-claude-defaults",
        ),
        pytest.param(
            {
                "llm_provider": {
                    "usage_metrics": {
                        "indicator": {"providers": {"claude": {"default": "never"}}}
                    }
                }
            },
            ("weekly:claude-fable-5",),
            id="broader-provider-default-loses-to-exact-window",
        ),
        pytest.param(
            {"llm_provider": {"usage_metrics": {"indicator": {"enabled": False}}}},
            (),
            id="indicator-disabled",
        ),
    ],
)
def test_usage_indicator_real_bundled_default_and_user_override_projection(
    user_config: Mapping[str, Any],
    expected: tuple[str, ...],
) -> None:
    _write_user_config(user_config)

    assert _projected_window_keys() == expected


def test_usage_indicator_bundled_fable_default_does_not_synthesize_missing_window() -> (
    None
):
    _clear_usage_indicator_cache()

    keys = _projected_window_keys(_claude_indicator_snapshot(include_fable=False))

    assert keys == ("session-low", "weekly")


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
