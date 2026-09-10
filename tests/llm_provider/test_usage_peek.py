"""Display-cache behavior for contextual usage hints."""

from __future__ import annotations

import pytest

from sase.llm_provider.usage import peek as peek_mod
from sase.llm_provider.usage.peek import (
    _clear_usage_peek_cache,
    cached_usage_indicator_projection,
    cached_usage_peek,
    refresh_usage_peek_cache,
    usage_attention_enabled,
    usage_peek_change_token,
)
from sase.llm_provider.usage.config import UsageIndicatorSettings, UsageMetricsSettings
from tests._rust_extension_module_helpers import install_fake_rust_extension
from tests.llm_provider._provider_config_helpers import mock_provider_config
from tests.llm_provider.test_usage_hints import _claude_model_specific_low


def test_config_opt_out_hides_planted_usage_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peek_mod._peek_providers = (_claude_model_specific_low(),)
    peek_mod._peek_eligible = frozenset({"claude"})
    try:
        mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": False}})
        assert usage_attention_enabled() is False
        providers, eligible = cached_usage_peek()
        assert providers == ()
        assert eligible == frozenset()
        mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
        assert usage_attention_enabled() is True
        providers, eligible = cached_usage_peek()
        assert providers
        assert "claude" in eligible
    finally:
        _clear_usage_peek_cache()


def test_projection_isolates_a_malformed_cached_snapshot() -> None:
    """A malformed memory-only snapshot must degrade, never crash widget construction."""
    peek_mod._peek_providers = ({"provider": "claude", "windows": []},)
    peek_mod._peek_snapshot = {
        "schema_version": 1,
        "generated_at": 100.0,
        "collection_health": "ok",
        "providers": [{"provider": "claude", "windows": []}],
        "attention": None,
    }
    peek_mod._peek_eligible = frozenset({"claude"})
    try:
        projection = cached_usage_indicator_projection(now=100.0)
    finally:
        _clear_usage_peek_cache()

    assert projection.entries == ()
    assert projection.providers == ()


def test_usage_peek_token_changes_when_config_changes_without_store_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _clear_usage_peek_cache()
    state_path = tmp_path / "missing-usage.json"
    current = ("config", 1)
    monkeypatch.setattr(peek_mod, "current_config_token", lambda: current)
    monkeypatch.setattr(peek_mod, "provider_usage_state_path", lambda: state_path)

    first = usage_peek_change_token()
    current = ("config", 2)
    second = usage_peek_change_token()

    assert first != second
    assert first[1] is None
    assert second[1] is None


def test_cached_projection_uses_memory_snapshot_and_indicator_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_usage_peek_cache()
    project_requests: list[dict[str, object]] = []

    def provider_usage_project_indicator(
        request: dict[str, object],
    ) -> dict[str, object]:
        project_requests.append(request)
        return {
            "schema_version": 1,
            "generated_at": request["now"],
            "enabled": True,
            "diagnostics": [],
            "providers": [{"provider": "claude"}],
            "entries": [{"provider": "claude", "window_key": "weekly"}],
        }

    install_fake_rust_extension(
        monkeypatch,
        provider_usage_project_indicator=provider_usage_project_indicator,
    )
    indicator = UsageIndicatorSettings(
        raw={"weekly_all": "always"},
        config={"enabled": True},
    )
    monkeypatch.setattr(
        peek_mod,
        "get_usage_metrics_settings",
        lambda: UsageMetricsSettings(
            enabled=True,
            refresh_seconds=120.0,
            warn_percent=70.0,
            critical_percent=85.0,
        ),
    )
    monkeypatch.setattr(peek_mod, "get_usage_indicator_settings", lambda: indicator)
    monkeypatch.setattr(
        peek_mod,
        "load_provider_usage",
        lambda **_kwargs: type(
            "Read",
            (),
            {
                "snapshot": {
                    "schema_version": 1,
                    "generated_at": 100.0,
                    "collection_health": "ok",
                    "providers": [{"provider": "claude", "windows": []}],
                    "attention": None,
                }
            },
        )(),
    )

    import sase.llm_provider.usage.refresh as refresh_mod

    monkeypatch.setattr(refresh_mod, "eligible_usage_providers", lambda: ("claude",))

    try:
        providers, eligible = refresh_usage_peek_cache(now=100.0)
        projection = cached_usage_indicator_projection(now=130.0)
    finally:
        _clear_usage_peek_cache()

    assert providers[0]["provider"] == "claude"
    assert eligible == frozenset({"claude"})
    assert projection.entries[0]["window_key"] == "weekly"
    assert project_requests == [
        {
            "schema_version": 1,
            "snapshot": {
                "schema_version": 1,
                "generated_at": 100.0,
                "collection_health": "ok",
                "providers": [{"provider": "claude", "windows": []}],
                "attention": None,
            },
            "indicator": {"weekly_all": "always"},
            "eligible_providers": ["claude"],
            "now": 130.0,
            "cadence_seconds": 120.0,
            "warn_percent": 70.0,
            "critical_percent": 85.0,
        }
    ]
