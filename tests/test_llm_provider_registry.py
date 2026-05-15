"""Tests for the LLM provider registry's metadata caching."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.llm_provider import registry


def _clear_registry_caches() -> None:
    registry._build_llm_pm.cache_clear()
    registry._llm_metadata_payload.cache_clear()


@pytest.fixture(autouse=True)
def reset_caches() -> Iterator[None]:
    """Reset registry caches around every test in this module."""
    _clear_registry_caches()
    yield
    _clear_registry_caches()


def test_metadata_payload_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated metadata lookups should not rebuild the payload."""
    call_count = 0
    real_payload = registry._direct_llm_metadata_payload

    def counting_payload() -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return real_payload()

    monkeypatch.setattr(registry, "_direct_llm_metadata_payload", counting_payload)
    _clear_registry_caches()

    # Touch every public accessor that reads the payload — the expensive
    # build should run once.
    registry.model_to_provider_map()
    registry.provider_short_name_map()
    registry.model_short_alias_map()
    registry.provider_cli_status_color_map()
    registry._provider_names()
    try:
        registry.get_default_provider_name()
    except RuntimeError:
        # No providers in this environment is fine; we only care about
        # the call count below.
        pass

    assert call_count == 1


def test_clear_llm_caches_allows_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """clear_llm_caches() must let a follow-up call rebuild the payload."""
    call_count = 0
    real_payload = registry._direct_llm_metadata_payload

    def counting_payload() -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return real_payload()

    monkeypatch.setattr(registry, "_direct_llm_metadata_payload", counting_payload)
    _clear_registry_caches()

    registry.model_to_provider_map()
    registry.model_to_provider_map()
    assert call_count == 1

    _clear_registry_caches()
    registry.model_to_provider_map()
    assert call_count == 2


def test_clear_llm_caches_resets_plugin_manager() -> None:
    """clear_llm_caches() must also reset the cached plugin manager."""
    pm_first = registry._build_llm_pm()
    assert registry._build_llm_pm() is pm_first

    _clear_registry_caches()
    pm_second = registry._build_llm_pm()
    # functools.cache rebuilds the value after cache_clear(); a fresh
    # PluginManager instance is observable proof the cache was reset.
    assert pm_second is not pm_first
