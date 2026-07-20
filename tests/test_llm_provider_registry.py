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


def test_provider_path_env_var_derives_from_name() -> None:
    """The SASE_<PROVIDER>_PATH override name is derived from the provider name."""
    assert registry.provider_path_env_var("agy") == "SASE_AGY_PATH"
    assert registry.provider_path_env_var("claude") == "SASE_CLAUDE_PATH"
    # Non-alphanumeric runs collapse to a single underscore.
    assert registry.provider_path_env_var("open-code") == "SASE_OPEN_CODE_PATH"


def test_cache_policy_env_names_are_derived_for_every_provider() -> None:
    """Cache invalidation must track each registered provider's path env var.

    The policy is derived from registered entry points rather than a hardcoded
    list, so a newly registered provider (e.g. ``agy``) participates without a
    one-off edit.
    """
    payload = registry.get_llm_metadata_payload()
    environment = payload["cache_invalidation"]["environment"]

    # Static, provider-independent invalidation inputs are always present.
    assert "SASE_DISABLE_PLUGINS" in environment
    assert "SASE_DISABLE_PLUGIN_LLM" in environment

    # Every registered provider contributes its derived path override.
    for provider_name in registry._provider_names():
        assert registry.provider_path_env_var(provider_name) in environment

    # agy specifically must be tracked now that it is registered.
    assert "SASE_AGY_PATH" in environment


def test_cache_policy_invalidates_on_provider_path_env_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing a provider's SASE_<PROVIDER>_PATH must change the cache policy."""
    monkeypatch.delenv("SASE_AGY_PATH", raising=False)
    before = registry._llm_metadata_cache_policy()["environment"]["SASE_AGY_PATH"]
    monkeypatch.setenv("SASE_AGY_PATH", "/opt/agy/agy")
    after = registry._llm_metadata_cache_policy()["environment"]["SASE_AGY_PATH"]

    assert before is None
    assert after == "/opt/agy/agy"


def test_provider_metadata_includes_auth_evidence() -> None:
    """Provider auth evidence metadata should be normalized into payloads."""

    class FakeProvider:
        def llm_provider_name(self) -> str:
            return "fake"

        def llm_auth_evidence(self) -> dict[str, list[str]]:
            return {
                "credential_paths": ["~/.fake/auth.json"],
                "api_key_env_vars": ["FAKE_API_KEY"],
            }

    metadata = registry._provider_metadata("fake", FakeProvider())

    assert metadata["auth_evidence"] == {
        "credential_paths": ["~/.fake/auth.json"],
        "api_key_env_vars": ["FAKE_API_KEY"],
        "auth_not_required": False,
    }


def test_provider_metadata_includes_install_metadata() -> None:
    """Provider install metadata should be normalized into payloads."""

    class FakeProvider:
        def llm_provider_name(self) -> str:
            return "fake"

        def llm_install_metadata(self) -> dict[str, str]:
            return {
                "manager": "npm",
                "package": "@example/fake",
                "scope": "global",
            }

    metadata = registry._provider_metadata("fake", FakeProvider())

    assert metadata["install"] == {
        "manager": "npm",
        "package": "@example/fake",
        "scope": "global",
    }


def test_provider_metadata_tolerantly_normalizes_update_fields() -> None:
    class FakeProvider:
        def llm_provider_name(self) -> str:
            return "fake"

        def llm_install_metadata(self) -> dict[str, object]:
            return {
                "manager": "npm",
                "package": "fake-cli",
                "scope": "global",
                "display_name": "Fake CLI",
                "docs_url": " https://example.test/fake ",
                "self_update_argv": ["upgrade", 1, ""],
                "version_argv": "invalid",
                "version_regex": r"version=(\d+)",
                "latest_version_package": "fake-cli",
                "unrecognized": {"future": True},
            }

    install = registry._provider_metadata("fake", FakeProvider())["install"]

    assert install == {
        "manager": "npm",
        "package": "fake-cli",
        "scope": "global",
        "display_name": "Fake CLI",
        "docs_url": "https://example.test/fake",
        "version_regex": r"version=(\d+)",
        "latest_version_package": "fake-cli",
        "self_update_argv": ["upgrade", "1"],
        "version_argv": ["--version"],
    }
