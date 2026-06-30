"""Tests for LLM provider registry and default model resolution."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.registry import (
    resolve_default_alias_provider_model,
    resolve_model_provider,
)
from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_effective_default_uses_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-directive launch routes through a configured ``@default`` alias."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_default_alias_provider_model() == ("codex", "gpt-5.5")
    assert resolve_effective_default_provider_model() == ("codex", "gpt-5.5")


def test_effective_default_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no configured ``default``, the provider tier default is used."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_default_alias_provider_model() == ("claude", "opus")
    assert resolve_default_alias_provider_model("small") == ("claude", "sonnet")
    assert resolve_effective_default_provider_model() == ("claude", "opus")


def test_active_override_wins_over_configured_default_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active primary override still wins the new-launch-default slot."""
    from sase.llm_provider.config import resolve_model_alias
    from sase.llm_provider.temporary_override import set_temporary_override

    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    set_temporary_override("agy/Gemini 3.5 Pro", 3600.0, source="test")

    # The override wins for the effective launch default ...
    assert resolve_effective_default_provider_model() == ("agy", "Gemini 3.5 Pro")
    # ... but an explicit @default reference still resolves to the configured
    # target (the override only wins the no-directive slot).
    assert resolve_default_alias_provider_model() == ("codex", "gpt-5.5")
    assert resolve_model_alias("default") == "codex/gpt-5.5"


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_explicit_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at explicit provider/model syntax."""
    mock_config.return_value = {"model_aliases": {"other": "claude/opus"}}

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_bare_alias(
    mock_config: MagicMock,
) -> None:
    """An alias can point at a known bare model name."""
    mock_config.return_value = {"model_aliases": {"other": "opus"}}

    assert resolve_model_provider("other") == ("claude", "opus")


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_provider_resolves_agy_display_name_alias(
    mock_config: MagicMock,
) -> None:
    """A model alias pointing at ``agy/<exact display name>`` routes to agy.

    This is the regression guard for the readable ``#agy_flash``/``#m_agy_flash``
    presets: the alias token expands to an explicit ``agy/<display name>`` target
    whose space-and-paren-laden model survives intact, so the launch routes to
    the Antigravity provider rather than falling back to the configured default.
    """
    mock_config.return_value = {
        "provider": "codex",
        "model_aliases": {"agy_flash": "agy/Gemini 3.5 Flash (High)"},
    }

    assert resolve_model_provider("agy_flash") == ("agy", "Gemini 3.5 Flash (High)")


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


def test_worker_alias_resolves_effective_worker_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "codex/gpt-5.5"}},
    )

    assert resolve_model_provider("worker") == ("codex", "gpt-5.5")


def test_worker_alias_shadows_configured_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {"claude": "codex/gpt-5.5"},
            "model_aliases": {"worker": "claude/sonnet"},
        },
    )

    assert resolve_model_provider("worker") == ("codex", "gpt-5.5")


def test_worker_alias_falls_through_to_primary_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_provider("worker") == ("claude", "opus")


def test_other_alias_uses_snapshot_when_override_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active override makes the internal ``other`` alias resolve to the displaced model."""
    from sase.llm_provider.temporary_override import set_temporary_override

    # Configured alias says claude/sonnet; configured default is claude -> opus.
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    set_temporary_override("codex/o3", 3600.0, source="test")

    # Snapshot captured claude/opus (the default that was displaced).
    assert resolve_model_provider("other") == ("claude", "opus")


def test_other_alias_uses_snapshot_even_without_configured_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override-driven snapshot fires even with no model_aliases.other configured."""
    from sase.llm_provider.temporary_override import set_temporary_override

    mock_provider_config(monkeypatch, {"provider": "claude"})

    set_temporary_override("codex/o3", 3600.0, source="test")

    assert resolve_model_provider("other") == ("claude", "opus")


def test_other_alias_falls_back_to_config_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an active override, the configured alias target wins."""
    mock_provider_config(monkeypatch, {"model_aliases": {"other": "claude/sonnet"}})

    assert resolve_model_provider("other") == ("claude", "sonnet")


def test_other_alias_falls_back_when_override_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After clear, "other" reverts to the configured alias target."""
    from sase.llm_provider.temporary_override import (
        clear_temporary_override,
        set_temporary_override,
    )

    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    set_temporary_override("codex/o3", 3600.0, source="test")
    clear_temporary_override()

    assert resolve_model_provider("other") == ("claude", "sonnet")


def test_other_alias_legacy_state_falls_back_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy state file (no snapshot fields) falls back to the configured alias."""
    from sase.llm_provider.temporary_override import _state_path

    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"other": "claude/sonnet"}},
    )

    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "codex",
                "model": "o3",
                "raw_model": "codex/o3",
                "created_at": time.time(),
                "expires_at": time.time() + 3600,
                "source": "ace",
            }
        ),
        encoding="utf-8",
    )

    # Snapshot fields absent; short-circuit declines and configured alias wins.
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
