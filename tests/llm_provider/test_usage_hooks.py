"""Hook contract: optional usage hooks, metadata cache, and invoke compatibility."""

from __future__ import annotations

import pluggy
import pytest

from sase.llm_provider import registry
from sase.llm_provider._hookspec import LLMHookSpec, hookimpl
from sase.llm_provider._plugin_manager import LLMPluginManager
from sase.llm_provider._registry_metadata import provider_metadata
from sase.llm_provider.types import InvokeResult, ModelTier
from sase.llm_provider.usage.probe import run_usage_probe
from sase.testing.usage_synthetic import (
    SYNTHETIC_PLUGIN_SPEC,
    _SyntheticUsageProvider,
)
from sase.llm_provider.usage.types import UsageProbeContext, observation_schema_version


def _legacy_plugin() -> object:
    class LegacyPlugin:
        @hookimpl
        def llm_invoke(
            self,
            prompt: str,
            model_tier: ModelTier,
            suppress_output: bool,
            model_override: str | None,
            options: object | None = None,
        ) -> InvokeResult:
            return InvokeResult(content=f"ok:{prompt}:{model_tier}")

        @hookimpl
        def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
            return f"legacy-{model_tier}"

        @hookimpl
        def llm_provider_name(self) -> str:
            return "legacy"

    return LegacyPlugin()


def _context(provider: str = "legacy") -> UsageProbeContext:
    return UsageProbeContext(
        schema_version=observation_schema_version(),
        provider=provider,
        deadline_at=1_800_000_010.0,
        context_id="ctx",
        account_generation=1,
        operation_id="op-1",
        request_started_at=1_800_000_000.0,
    )


def test_omitted_usage_hooks_mean_unsupported_capabilities() -> None:
    metadata = provider_metadata("legacy", _legacy_plugin())
    assert metadata["usage_capabilities"] == {"probe": False, "passive_events": False}
    assert "windows" not in metadata
    assert "observation" not in metadata


def test_synthetic_capabilities_are_cached_without_observations() -> None:
    metadata = provider_metadata("synth", _SyntheticUsageProvider())
    assert metadata["usage_capabilities"] == {"probe": True, "passive_events": False}
    assert "windows" not in metadata


def test_legacy_plugin_still_invokes_without_usage_hooks() -> None:
    pm = pluggy.PluginManager("sase_llm")
    pm.add_hookspecs(LLMHookSpec)
    pm.register(_legacy_plugin())
    manager = LLMPluginManager(pm)
    result = manager.invoke("hello", model_tier="large")
    assert result == InvokeResult(content="ok:hello:large")
    assert manager.resolve_model_name("small") == "legacy-small"


def test_legacy_plugin_probe_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    result = run_usage_probe(
        _context("legacy"),
        isolate=False,
        plugin=_legacy_plugin(),
        now=1_800_000_000.0,
    )
    assert result.skipped is None
    assert result.observation is not None
    assert result.observation["outcome"] == "unsupported"
    assert result.observation["windows"] == []


def test_probe_does_not_enter_registry_metadata_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    run_usage_probe(
        _context("synth"),
        isolate=False,
        plugin=_SyntheticUsageProvider(),
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        now=1_800_000_000.0,
    )
    registry._build_llm_pm.cache_clear()
    registry._llm_metadata_payload.cache_clear()
    payload = registry._direct_llm_metadata_payload()
    for metadata in payload["providers"].values():
        assert "windows" not in metadata
        assert metadata["usage_capabilities"]["probe"] in {True, False}
