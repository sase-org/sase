"""Tests for LLM provider registry and default model resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import yaml  # type: ignore[import-untyped]

import pytest

from sase.llm_provider import model_alias_policy
from sase.llm_provider.registry import (
    resolve_default_alias_provider_model,
    resolve_default_alias_provider_model_with_effort,
    resolve_model_provider,
)
from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model,
    resolve_effective_default_provider_model_with_effort,
)
from sase.llm_provider.model_alias_policy import SMARTER_MODEL_ALIAS_NAME
from tests._model_alias_defaults_fixture import (
    frozen_alias_defaults_yaml,
    frozen_selector_provider_model_effort,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_effective_default_uses_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-directive launch routes through a configured ``@default`` alias."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    assert resolve_default_alias_provider_model() == ("codex", "gpt-5.6-sol")
    assert resolve_effective_default_provider_model() == ("codex", "gpt-5.6-sol")


def test_unconfigured_default_routes_through_shipped_fallback_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no configured ``default``, the shipped fallback pool is authoritative."""
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )

    first = resolve_effective_default_provider_model_with_effort(consume=True)
    second = resolve_effective_default_provider_model_with_effort(consume=True)

    assert first == frozen_selector_provider_model_effort(SMARTER_MODEL_ALIAS_NAME, 0)
    assert second == frozen_selector_provider_model_effort(SMARTER_MODEL_ALIAS_NAME, 1)


def test_default_without_shipped_fallback_uses_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The terminal provider default still honors the requested model tier."""
    aliases = yaml.safe_load(frozen_alias_defaults_yaml())["aliases"]
    aliases["default"] = {"description": "Default with no shipped fallback."}
    defaults = model_alias_policy._parse_model_alias_defaults(
        frozen_alias_defaults_yaml(aliases),
        source="test",
    )
    monkeypatch.setattr(
        model_alias_policy, "_load_model_alias_defaults", lambda: defaults
    )
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_default_alias_provider_model() == ("claude", "opus")
    assert resolve_default_alias_provider_model("small") == ("claude", "sonnet")
    assert resolve_default_alias_provider_model_with_effort("small") == (
        "claude",
        "sonnet",
        None,
    )
    assert resolve_effective_default_provider_model() == ("claude", "opus")


def test_active_override_replaces_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active override wins both launch and explicit default resolution."""
    from sase.llm_provider.config import resolve_model_alias
    from sase.llm_provider.temporary_override import set_temporary_override

    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
        },
    )

    set_temporary_override("agy/custom-pro", 3600.0, source="test")

    assert resolve_effective_default_provider_model() == ("agy", "custom-pro")
    assert resolve_default_alias_provider_model() == ("agy", "custom-pro")
    assert resolve_model_alias("default") == "agy/custom-pro"


def test_active_override_replaces_unconfigured_provider_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry honors an override even without configured ``default``."""
    from sase.llm_provider.temporary_override import set_temporary_override

    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3@medium", 3600.0, source="test")

    assert resolve_default_alias_provider_model("small") == ("codex", "o3")
    assert resolve_default_alias_provider_model_with_effort("small") == (
        "codex",
        "o3",
        "medium",
    )


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_explicit_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at explicit provider/model syntax."""
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                "other": {
                    "model": "claude/opus",
                    "description": "Other model.",
                }
            }
        }
    }

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_bare_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at a known bare model name."""
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                "other": {
                    "model": "opus",
                    "description": "Other model.",
                }
            }
        }
    }

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_agy_display_name_alias(
    mock_config: MagicMock,
) -> None:
    """A model alias pointing at ``agy/<exact model slug>`` routes to agy.

    This is the regression guard for the readable ``#agy_flash``/``#m_agy_flash``
    presets: the alias token expands to an explicit ``agy/<model slug>`` target
    whose model slug survives intact, so the launch routes to the Antigravity
    provider rather than falling back to the configured default.
    """
    mock_config.return_value = {
        "provider": "codex",
        "model_aliases": {
            "custom": {
                "agy_flash": {
                    "model": "agy/gemini-3.5-flash-high",
                    "description": "Antigravity flash preset.",
                }
            }
        },
    }

    assert resolve_model_provider("agy_flash") == ("agy", "gemini-3.5-flash-high")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_unknown_agy_token_falls_back(
    mock_config: MagicMock,
) -> None:
    """Without the alias, ``agy_flash`` keeps the documented default fallback.

    When the ``agy_flash`` alias is missing from ``model_aliases`` (the broken
    state this work fixes), the bare token is unknown to every provider, so
    resolution returns ``(None, ...)`` and the launch falls back to the
    configured default provider. The doctor guard (not a hard error) is what
    surfaces this degradation.
    """
    mock_config.return_value = {"provider": "codex", "model_aliases": {}}

    assert resolve_model_provider("agy_flash") == (None, "agy_flash")


def test_worker_and_other_are_not_special_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker``/``other`` carry no implicit resolution after phase 4.

    The worker lane was retired in epic sase-5d phase 4, so neither name has
    special behavior: ``worker`` is an unknown bare token, while a configured
    ``other`` resolves through its target like any ordinary alias. An active
    primary override no longer gives ``other`` any displacement magic.
    """
    from sase.llm_provider.temporary_override import set_temporary_override

    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "other": {
                        "model": "claude/sonnet",
                        "description": "Other model.",
                    }
                }
            },
        },
    )
    set_temporary_override("codex/o3", 3600.0, source="test")

    assert resolve_model_provider("worker") == (None, "worker")
    assert resolve_model_provider("other") == ("claude", "sonnet")


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_codex(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that codex is auto-detected when claude is absent."""
    mock_which.side_effect = lambda name: "/usr/bin/codex" if name == "codex" else None

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "codex"


@patch("sase.llm_provider.registry.shutil.which")
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_priority(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that claude wins over codex when both are available."""
    mock_which.side_effect = lambda name: f"/usr/bin/{name}"

    from sase.llm_provider.registry import get_default_provider_name

    assert get_default_provider_name() == "claude"


@patch(
    "sase.llm_provider.registry._llm_metadata_payload",
    return_value={
        "autodetect_candidates": [
            {"priority": 30, "provider": "agy", "cli_name": "agy"}
        ]
    },
)
@patch("sase.llm_provider.registry.shutil.which", return_value=None)
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_registry_auto_detect_does_not_select_missing_agy_fallback(
    mock_config: MagicMock,
    mock_which: MagicMock,
    mock_payload: MagicMock,
) -> None:
    """Antigravity is not selected unless the `agy` CLI is discoverable."""
    from sase.llm_provider.registry import get_default_provider_name

    with pytest.raises(RuntimeError, match="No LLM provider is available"):
        get_default_provider_name()
