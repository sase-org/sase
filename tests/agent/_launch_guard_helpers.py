"""Shared fixtures for the fail-closed launch-guard tests."""

from __future__ import annotations

import pytest

from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def disable(
    provider: str,
    *,
    mode: str = PROVIDER_DISABLE_MODE_HARD,
    expires_at: float | None = 1_000.0,
    source: str = "ace",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source=source,
        mode=mode,
    )


def pin_cli_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda _provider: True,
    )


def pin_default_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "codex", "default_model": "codex/gpt-5.5"},
    )


def install_disables(
    monkeypatch: pytest.MonkeyPatch,
    disables: dict[str, TemporaryProviderDisable],
) -> None:
    snapshot = dict(disables)

    def _snapshot(_now: float | None = None) -> dict[str, TemporaryProviderDisable]:
        return dict(snapshot)

    monkeypatch.setattr(
        "sase.agent.launch_guard.peek_active_provider_disables",
        _snapshot,
    )
    monkeypatch.setattr(
        "sase.llm_provider.provider_disable_peek.peek_active_provider_disables",
        _snapshot,
    )
    monkeypatch.setattr(
        "sase.llm_provider.launch_selection.get_active_provider_disables",
        _snapshot,
    )
    monkeypatch.setattr(
        "sase.llm_provider.provider_disable.get_active_provider_disables",
        _snapshot,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_active_provider_disables",
        _snapshot,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.capture_provider_disable_snapshot",
        _snapshot,
    )
