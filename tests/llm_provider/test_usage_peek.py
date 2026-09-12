"""Display-cache behavior for contextual usage hints."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
)
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
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._rust_extension_module_helpers import install_fake_rust_extension
from tests._usage_view_helpers import usage_provider, usage_window
from tests.llm_provider._provider_config_helpers import mock_provider_config
from tests.llm_provider.test_usage_hints import _claude_model_specific_low

_FROZEN_NOW = 1_800_000_000.0


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


def _weekly_account_window(
    *, key: str, label: str, remaining_percent: float, resets_at: float
) -> dict[str, object]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=max(0.0, 100.0 - remaining_percent),
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        applicability={"kind": "account"},
    )
    window["duration_seconds"] = 604_800.0
    return window


def test_codex_nvm_weekly_window_reaches_header_through_real_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Codex install only resolvable via NVM_BIN must clear real eligibility.

    Exercises the real eligibility check (including the Codex NVM-fallback
    fix in ``_provider_cli_ready``), real peek-cache loading, and the real
    Rust indicator projection end to end. Only provider metadata,
    configuration, the snapshot load, and the clock are supplied by the test.
    """
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["codex", "grok"],
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.model_picker_hidden_provider_names",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "codex": {
                    "autodetect_cli_name": "codex",
                    "usage_capabilities": {"probe": True},
                },
                "grok": {"usage_capabilities": {"probe": True}},
            }
        },
    )
    mock_provider_config(
        monkeypatch,
        {
            "usage_metrics": {
                "enabled": True,
                "providers": {"codex": True, "grok": True},
                "indicator": {"enabled": True, "weekly_all": "always"},
            }
        },
    )

    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))
    monkeypatch.delenv("SASE_CODEX_PATH", raising=False)
    nvm_bin = tmp_path / "nvm-bin"
    nvm_bin.mkdir()
    codex_bin = nvm_bin / "codex"
    codex_bin.write_text("#!/bin/sh\n")
    codex_bin.chmod(0o755)
    monkeypatch.setenv("NVM_BIN", str(nvm_bin))

    codex_window = _weekly_account_window(
        key="primary",
        label="Codex weekly",
        remaining_percent=99.0,
        resets_at=_FROZEN_NOW + 601_200.0,
    )
    grok_window = _weekly_account_window(
        key="weekly",
        label="Grok weekly",
        remaining_percent=59.0,
        resets_at=_FROZEN_NOW + 536_400.0,
    )
    snapshot = {
        "schema_version": 1,
        "generated_at": _FROZEN_NOW,
        "collection_health": "ok",
        "providers": [
            usage_provider(
                "codex",
                used_percent=1.0,
                remaining_percent=99.0,
                windows=[codex_window],
                known_constraints=[],
            ),
            usage_provider(
                "grok",
                used_percent=41.0,
                remaining_percent=59.0,
                windows=[grok_window],
                known_constraints=[],
            ),
        ],
        "attention": None,
    }
    monkeypatch.setattr(
        peek_mod,
        "load_provider_usage",
        lambda **_kwargs: type("Read", (), {"snapshot": snapshot})(),
    )

    try:
        _providers, eligible = refresh_usage_peek_cache(now=_FROZEN_NOW)
        projection = cached_usage_indicator_projection(now=_FROZEN_NOW)
    finally:
        _clear_usage_peek_cache()

    assert eligible == frozenset({"codex", "grok"})
    codex_entries = [
        entry for entry in projection.entries if entry["provider"] == "codex"
    ]
    assert len(codex_entries) == 1
    codex_entry = codex_entries[0]
    assert codex_entry["period"]["kind"] == "weekly"
    assert codex_entry["scope"]["kind"] == "all_models"
    assert codex_entry["policy_source"] == "weekly_all"

    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=_FROZEN_NOW)
    )
    assert "🤖 99%" in segment.plain

    hidden_projection = provider_usage_project_indicator(
        snapshot,
        indicator={
            "weekly_all": "always",
            "providers": {"codex": {"windows": {"primary": "never"}}},
        },
        eligible_providers=eligible,
        now=_FROZEN_NOW,
    )
    assert all(entry["provider"] != "codex" for entry in hidden_projection.entries)
    assert any(entry["provider"] == "grok" for entry in hidden_projection.entries)
