"""Tests for tmux Agent catalog assembly."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.config.tmux_agent import TmuxAgentConfig, TmuxAgentProviderConfig
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    TemporaryProviderDisable,
)
from sase.tmux_agent import catalog as catalog_module
from sase.tmux_agent.catalog import build_tmux_agent_catalog


def _status(
    name: str,
    *,
    installed: bool,
    display_name: str = "",
) -> AgentCliStatus:
    executable = f"/usr/bin/{name}" if installed else None
    return AgentCliStatus(
        name=name,
        display_name=display_name or name,
        binary=name,
        executable=executable,
        installed_version="1.0.0" if installed else None,
        latest_version=None,
        install_method=InstallMethod.NPM if installed else InstallMethod.NOT_INSTALLED,
        update_available=False,
        docs_url=None,
        install_hint=f"install {name} first",
    )


@pytest.fixture(autouse=True)
def _stable_catalog_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the impure, catalog-level inputs so tests control them directly."""
    monkeypatch.setattr(
        catalog_module, "get_tmux_agent_config", lambda: TmuxAgentConfig()
    )
    monkeypatch.setattr(catalog_module, "get_llm_provider_config", lambda: {})
    monkeypatch.setattr(
        catalog_module,
        "effective_default_effort_snapshot",
        lambda now=None: SimpleNamespace(effective_effort=lambda now=None: None),
    )
    monkeypatch.setattr(
        catalog_module, "get_active_provider_disables", lambda now=None: {}
    )


def test_installed_and_not_installed_providers_both_appear() -> None:
    statuses = (_status("claude", installed=True), _status("codex", installed=False))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert {entry.provider for entry in result.entries} == {"claude", "codex"}
    by_name = {entry.provider: entry for entry in result.entries}
    assert by_name["claude"].installed is True
    assert by_name["codex"].installed is False
    assert by_name["codex"].install_hint == "install codex first"


def test_fakey_is_excluded_even_when_a_status_is_injected() -> None:
    statuses = (_status("claude", installed=True), _status("fakey", installed=True))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert "fakey" not in {entry.provider for entry in result.entries}


def test_config_disabled_provider_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog_module,
        "get_tmux_agent_config",
        lambda: TmuxAgentConfig(
            providers={"codex": TmuxAgentProviderConfig(enabled=False)}
        ),
    )
    statuses = (_status("claude", installed=True), _status("codex", installed=True))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert {entry.provider for entry in result.entries} == {"claude"}


def test_entries_are_ordered_by_assigned_key_then_provider_name() -> None:
    statuses = (
        _status("codex", installed=True),
        _status("claude", installed=True),
        _status("agy", installed=True),
    )

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    keys = [entry.key for entry in result.entries]
    assert keys == sorted(keys)
    assert [entry.provider for entry in result.entries] == ["agy", "claude", "codex"]


def test_directory_is_passed_through() -> None:
    result = build_tmux_agent_catalog(directory="/some/dir", statuses=())
    assert result.directory == "/some/dir"


def test_nothing_installed_yields_no_default_provider() -> None:
    statuses = (_status("claude", installed=False), _status("codex", installed=False))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert result.default_provider is None


def test_default_provider_prefers_configured_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog_module, "get_llm_provider_config", lambda: {"provider": "codex"}
    )
    statuses = (_status("claude", installed=True), _status("codex", installed=True))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert result.default_provider == "codex"


def test_default_provider_ignores_configured_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog_module, "get_llm_provider_config", lambda: {"provider": "codex"}
    )
    statuses = (_status("claude", installed=True), _status("codex", installed=False))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert result.default_provider == "claude"


def test_default_provider_falls_back_to_highest_autodetect_priority() -> None:
    statuses = (_status("claude", installed=True), _status("codex", installed=True))

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    payload = catalog_module.llm_registry.get_llm_metadata_payload()["providers"]
    claude_priority = payload["claude"]["autodetect_priority"]
    codex_priority = payload["codex"]["autodetect_priority"]
    assert isinstance(claude_priority, int)
    assert isinstance(codex_priority, int)
    expected = "claude" if claude_priority <= codex_priority else "codex"
    assert result.default_provider == expected


def test_default_provider_falls_back_to_first_installed_entry_in_menu_order() -> None:
    statuses = (_status("claude", installed=True),)

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert result.default_provider == "claude"
    assert result.entries[0].provider == "claude"


def test_routing_disabled_annotates_but_does_not_exclude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable = TemporaryProviderDisable(
        version=2,
        provider="claude",
        created_at=0.0,
        expires_at=None,
        source="test",
        mode=PROVIDER_DISABLE_MODE_HARD,
    )
    monkeypatch.setattr(
        catalog_module,
        "get_active_provider_disables",
        lambda now=None: {"claude": disable},
    )
    statuses = (_status("claude", installed=True),)

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    assert len(result.entries) == 1
    assert result.entries[0].routing_disabled == disable


def test_effort_and_bypass_flow_through_to_entries() -> None:
    statuses = (_status("claude", installed=True),)

    result = build_tmux_agent_catalog(directory="/tmp", statuses=statuses)

    entry = result.entries[0]
    assert entry.bypass is True
    assert "--dangerously-skip-permissions" in entry.argv
