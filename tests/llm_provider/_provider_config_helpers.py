"""Shared helpers for LLM provider config tests."""

from __future__ import annotations

import pytest


def mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    """Patch the config lookup at every module that imported it directly."""
    from sase.llm_provider import config as llm_provider_config

    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )
    llm_provider_config._get_model_aliases_for_token.cache_clear()


def patch_available_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin registered and available providers for deterministic view tests."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex"],
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
