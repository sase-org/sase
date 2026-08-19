"""Tests for the ``tmux_agent`` configuration section."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.tmux_agent import (
    TmuxAgentConfig,
    TmuxAgentProviderConfig,
    get_tmux_agent_config,
)
from tests._config_schema_helpers import schema

_EFFORT_ENUM = ("", "off", "none", "minimal", "low", "medium", "high", "xhigh", "max")


def _validate(config: dict[str, Any]) -> None:
    Draft7Validator(schema()).validate(config)


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        "sase.config.tmux_agent.load_merged_config",
        lambda: config,
    )
    monkeypatch.setattr(
        "sase.config.tmux_agent.current_config_token",
        lambda: ("tmux-agent-test", id(config)),
    )


def test_defaults_with_no_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch, {})

    cfg = get_tmux_agent_config()

    assert cfg == TmuxAgentConfig()
    assert cfg.window_name == "ai"
    assert cfg.bypass_permissions is True
    assert cfg.effort == ""
    assert cfg.clear_screen is True
    assert cfg.after_close_command == ""
    assert dict(cfg.providers) == {}


def test_shipped_defaults_include_claude_example() -> None:
    cfg = get_tmux_agent_config()

    assert cfg.window_name == "ai"
    assert cfg.bypass_permissions is True
    assert cfg.effort == ""
    assert cfg.clear_screen is True
    assert cfg.after_close_command == ""
    assert "claude" in cfg.providers
    claude = cfg.providers["claude"]
    assert claude.enabled is True
    assert claude.key == ""
    assert claude.model == ""
    assert claude.effort == ""
    assert claude.args == ()
    assert dict(claude.env) == {}
    assert claude.bypass_permissions is True


def test_full_user_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch,
        {
            "tmux_agent": {
                "window_name": "agent",
                "bypass_permissions": False,
                "effort": "high",
                "clear_screen": False,
                "after_close_command": "echo done",
                "providers": {
                    "codex": {
                        "enabled": False,
                        "key": "x",
                        "model": "gpt-5.6",
                        "effort": "xhigh",
                        "args": ["--foo", "bar"],
                        "env": {"EDITOR": "nvim"},
                        "bypass_permissions": False,
                    }
                },
            }
        },
    )

    cfg = get_tmux_agent_config()

    assert cfg.window_name == "agent"
    assert cfg.bypass_permissions is False
    assert cfg.effort == "high"
    assert cfg.clear_screen is False
    assert cfg.after_close_command == "echo done"
    assert set(cfg.providers) == {"codex"}
    codex = cfg.providers["codex"]
    assert codex == TmuxAgentProviderConfig(
        enabled=False,
        key="x",
        model="gpt-5.6",
        effort="xhigh",
        args=("--foo", "bar"),
        env={"EDITOR": "nvim"},
        bypass_permissions=False,
    )


def test_per_provider_bypass_permissions_absent_inherits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {"tmux_agent": {"providers": {"claude": {"enabled": True}}}},
    )

    cfg = get_tmux_agent_config()

    assert cfg.bypass_permissions is True
    assert cfg.providers["claude"].bypass_permissions is None


def test_per_provider_bypass_permissions_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "tmux_agent": {
                "bypass_permissions": True,
                "providers": {"claude": {"bypass_permissions": False}},
            }
        },
    )

    assert get_tmux_agent_config().providers["claude"].bypass_permissions is False


@pytest.mark.parametrize("bad_key", ["ab", " ", "\t", "ctrl+c", 1])
def test_invalid_key_is_dropped_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    bad_key: object,
) -> None:
    _patch_config(
        monkeypatch,
        {"tmux_agent": {"providers": {"claude": {"key": bad_key}}}},
    )

    with caplog.at_level(logging.WARNING):
        cfg = get_tmux_agent_config()

    assert cfg.providers["claude"].key == ""
    assert "tmux_agent.providers.claude.key" in caplog.text


def test_unknown_provider_name_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(
        monkeypatch,
        {
            "tmux_agent": {
                "providers": {
                    "not-a-real-provider": {
                        "enabled": False,
                        "model": "custom",
                    }
                }
            }
        },
    )

    cfg = get_tmux_agent_config()

    assert "not-a-real-provider" in cfg.providers
    unknown = cfg.providers["not-a-real-provider"]
    assert unknown.enabled is False
    assert unknown.model == "custom"


@pytest.mark.parametrize("effort", _EFFORT_ENUM)
def test_schema_accepts_effort_enum(effort: str) -> None:
    _validate({"tmux_agent": {"effort": effort}})
    _validate({"tmux_agent": {"providers": {"claude": {"effort": effort}}}})


@pytest.mark.parametrize("effort", ["turbo", "MAX", 1, True, "off "])
def test_schema_rejects_invalid_effort(effort: object) -> None:
    with pytest.raises(ValidationError):
        _validate({"tmux_agent": {"effort": effort}})
    with pytest.raises(ValidationError):
        _validate({"tmux_agent": {"providers": {"claude": {"effort": effort}}}})


def test_schema_rejects_unknown_tmux_agent_keys() -> None:
    with pytest.raises(ValidationError):
        _validate({"tmux_agent": {"unknown_field": True}})
    with pytest.raises(ValidationError):
        _validate({"tmux_agent": {"providers": {"claude": {"unknown_field": True}}}})


def test_schema_accepts_full_section() -> None:
    _validate(
        {
            "tmux_agent": {
                "window_name": "ai",
                "bypass_permissions": True,
                "effort": "off",
                "clear_screen": False,
                "after_close_command": "",
                "providers": {
                    "claude": {
                        "enabled": True,
                        "key": "c",
                        "model": "",
                        "effort": "",
                        "args": ["--verbose"],
                        "env": {"EDITOR": "nvim"},
                    }
                },
            }
        }
    )


def test_malformed_section_degrades_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_config(monkeypatch, {"tmux_agent": "not-a-mapping"})

    with caplog.at_level(logging.WARNING):
        cfg = get_tmux_agent_config()

    assert cfg == TmuxAgentConfig()
    assert "expected a mapping" in caplog.text
