"""Tests for LLM provider model alias configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider.config import (
    _get_configured_worker_models,
    _get_model_aliases,
    coder_model_alias_for_provider,
    default_model_alias_name,
    format_model_directive_value,
    get_configured_worker_model_entry_for_primary,
    model_alias_names,
    resolve_model_alias,
    role_model_directive_value,
)
from sase.llm_provider.registry import resolve_model_provider
from tests.llm_provider._provider_config_helpers import mock_provider_config


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_aliases_ignore_invalid_entries(mock_config: MagicMock) -> None:
    """Model aliases are stripped and invalid keys/values are ignored."""
    mock_config.return_value = {
        "model_aliases": {
            " other ": " claude/opus ",
            123: "opus",
            "empty": "   ",
            "bad": ["opus"],
        }
    }

    assert _get_model_aliases() == {"other": "claude/opus"}


@patch("sase.llm_provider.config._registered_provider_names")
@patch("sase.llm_provider.config.get_llm_provider_config")
def test_model_alias_names_include_configured_special_and_legacy(
    mock_config: MagicMock,
    mock_providers: MagicMock,
) -> None:
    """``model_alias_names`` unions configured, special, and legacy aliases."""
    mock_config.return_value = {"model_aliases": {"fast": "codex/o4-mini"}}
    mock_providers.return_value = ["claude", "codex"]

    assert model_alias_names() == {
        # user-configured
        "fast",
        # fixed implicit role aliases
        "default",
        "coder",
        "epic_creator",
        "epic_lander",
        "phase_worker",
        # per-provider coder aliases
        "claude_coder",
        "codex_coder",
        # legacy reserved (deprecated stubs, retired in epic sase-5d phases 3-4)
        "worker",
        "other",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_format_model_directive_value_adds_alias_prefix(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "fast": "codex/o4-mini",
            "other": "claude/opus",
        }
    }

    assert format_model_directive_value("worker") == "@worker"
    assert format_model_directive_value("other") == "@other"
    assert format_model_directive_value("fast") == "@fast"
    assert format_model_directive_value("@worker") == "@worker"
    assert format_model_directive_value("opus") == "opus"
    assert format_model_directive_value("claude/opus") == "claude/opus"


@patch("sase.llm_provider.config.get_llm_provider_config")
@pytest.mark.parametrize(
    "cfg",
    [
        {},
        {"worker_model": "codex/gpt-5.5"},
        {"worker_models": ""},
        {"worker_models": "   "},
        {"worker_models": 123},
        {"worker_models": ["codex/gpt-5.5"]},
        {
            "worker_models": {
                "": "codex/gpt-5.5",
                "claude": "",
                "codex": "   ",
                123: "opus",
                "bad": ["codex/gpt-5.5"],
            }
        },
    ],
)
def test_get_configured_worker_models_tolerates_missing_blank_and_malformed(
    mock_config: MagicMock,
    cfg: dict[str, object],
) -> None:
    mock_config.return_value = cfg

    assert _get_configured_worker_models() == {}


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_get_configured_worker_models_strips_keys_and_values(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "worker_models": {
            " claude ": " codex/gpt-5.5 ",
            " opus ": " claude/sonnet ",
        }
    }

    assert _get_configured_worker_models() == {
        "claude": "codex/gpt-5.5",
        "opus": "claude/sonnet",
    }


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_get_configured_worker_model_entry_uses_specificity_order(
    mock_config: MagicMock,
) -> None:
    """The entry helper returns the most specific matched key and its target."""
    mock_config.return_value = {
        "worker_models": {
            "claude": "qwen/qwen3.6-plus",
            "opus": "agy/flash35h",
            "claude/opus": "codex/gpt-5.5",
        }
    }

    assert get_configured_worker_model_entry_for_primary("claude", "opus") == (
        "claude/opus",
        "codex/gpt-5.5",
    )
    assert get_configured_worker_model_entry_for_primary("opencode", "opus") == (
        "opus",
        "agy/flash35h",
    )
    assert get_configured_worker_model_entry_for_primary("claude", "sonnet") == (
        "claude",
        "qwen/qwen3.6-plus",
    )
    assert get_configured_worker_model_entry_for_primary("codex", "o3") is None


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_alias_handles_chains_and_cycles(
    mock_config: MagicMock,
) -> None:
    """Alias chains resolve, but cycles fall back to the raw input."""
    mock_config.return_value = {
        "model_aliases": {
            "other": "review",
            "review": "opus",
            "a": "b",
            "b": "a",
        }
    }

    assert resolve_model_alias("other") == "opus"
    assert resolve_model_alias("missing") == "missing"
    assert resolve_model_alias("a") == "a"


def test_role_alias_helpers() -> None:
    """The role-alias name/directive helpers return the documented strings."""
    assert default_model_alias_name() == "default"
    assert coder_model_alias_for_provider("codex") == "codex_coder"
    assert coder_model_alias_for_provider(" claude ") == "claude_coder"
    assert role_model_directive_value("phase_worker") == "@phase_worker"
    assert role_model_directive_value("default") == "@default"


def test_default_alias_resolves_to_configured_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured ``default`` resolves through its explicit provider/model."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_model_alias("default") == "codex/gpt-5.5"
    assert resolve_model_provider("default") == ("codex", "gpt-5.5")


def test_default_alias_falls_back_to_provider_tier_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent a configured ``default``, ``@default`` is the provider tier default."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("default") == "claude/opus"
    assert resolve_model_provider("default") == ("claude", "opus")


def test_coder_alias_chains_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``coder`` defaults to ``@default`` when not explicitly configured."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    assert resolve_model_alias("coder") == "codex/gpt-5.5"
    assert resolve_model_provider("coder") == ("codex", "gpt-5.5")


def test_provider_coder_alias_chains_to_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``<provider>_coder`` defaults to ``@coder`` -> ``@default`` when unset."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    # codex is a registered provider, so codex_coder is an implicit alias.
    assert resolve_model_alias("codex_coder") == "codex/gpt-5.5"
    assert resolve_model_provider("codex_coder") == ("codex", "gpt-5.5")


def test_epic_role_aliases_chain_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """epic_creator / epic_lander / phase_worker default to ``@default``."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "codex/gpt-5.5"}},
    )

    for role in ("epic_creator", "epic_lander", "phase_worker"):
        assert resolve_model_alias(role) == "codex/gpt-5.5"


def test_configured_role_alias_shadows_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-configured role alias wins over the implicit ``@default`` fallback."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "default": "codex/gpt-5.5",
                "phase_worker": "claude/sonnet",
            },
        },
    )

    assert resolve_model_alias("phase_worker") == "claude/sonnet"
    assert resolve_model_alias("coder") == "codex/gpt-5.5"  # still @default


def test_alias_value_may_reference_another_alias_with_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values can reference other aliases with the ``@`` marker."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "fast": "codex/o4-mini",
                "claude_coder": "@fast",
            },
        },
    )

    assert resolve_model_alias("claude_coder") == "codex/o4-mini"
    assert resolve_model_provider("claude_coder") == ("codex", "o4-mini")


def test_alias_at_reference_cycle_falls_back_to_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cyclic ``@`` reference chain fails closed to the original input."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"x": "@y", "y": "@x"}},
    )

    assert resolve_model_alias("x") == "x"


def test_self_referential_default_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``default: @default`` self-cycle is detected and never recurses."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"default": "@default"}},
    )

    # Fails closed to the input rather than recursing on the special branch.
    assert resolve_model_alias("default") == "default"


def test_unknown_at_reference_resolves_to_bare_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling ``@`` reference to a non-alias resolves to the bare token."""
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    # `@nope` references an alias that is neither configured nor special.
    assert resolve_model_alias("@nope") == "nope"


def test_worker_and_other_retained_as_legacy_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker``/``other`` remain valid legacy stubs until phases 3-4 retire them.

    Phase 1 keeps the worker lane functional because the plan/bead emit sites
    and worker-override UI that still produce ``@worker``/``@other`` are owned by
    epic sase-5d phases 3-4. They stay in the alias-name policy so directive
    validation does not reject prompts those phases still render.
    """
    from sase.llm_provider.config import special_model_alias_names

    mock_provider_config(monkeypatch, {"provider": "claude"})

    names = special_model_alias_names()
    assert {"worker", "other"} <= names
    # The new role aliases are advertised alongside the legacy ones.
    assert {"default", "coder", "epic_creator", "epic_lander", "phase_worker"} <= names
