"""Tests for temporary LLM override provider/model resolution."""

from __future__ import annotations

import json
import time

import pytest

from sase.llm_provider.temporary_override import (
    _state_path,
    resolve_effective_default_provider_model,
    resolve_effective_worker_provider_model,
    resolve_worker_provider_model_for_primary,
    set_temporary_override,
)
from tests.llm_provider._temporary_override_helpers import mock_provider_config


# ---------------------------------------------------------------------------
# resolve_effective_default_provider_model
# ---------------------------------------------------------------------------


def test_resolve_effective_default_no_override() -> None:
    provider, model = resolve_effective_default_provider_model()
    assert provider in {"claude", "codex", "gemini"}
    assert isinstance(model, str) and model


def test_resolve_effective_default_with_override() -> None:
    set_temporary_override("codex/o3", 3600.0, source="ace")
    provider, model = resolve_effective_default_provider_model()
    assert provider == "codex"
    assert model == "o3"


def test_resolve_effective_default_ignores_expired_override() -> None:
    set_temporary_override("codex/o3", 60.0, source="ace")
    # Force the override to be in the past by rewriting state.
    path = _state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    provider, _ = resolve_effective_default_provider_model()
    assert provider != "codex" or _ != "o3"
    # And the stale state file is cleaned up by the read.
    assert not path.exists()


# ---------------------------------------------------------------------------
# resolve_effective_worker_provider_model
# ---------------------------------------------------------------------------


def test_resolve_effective_worker_prefers_worker_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "gemini/gemini-2.5-pro"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")
    set_temporary_override("codex/gpt-5.5", 3600.0, source="ace", role="worker")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_provider_syntax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "codex/gpt-5.5"}},
    )
    set_temporary_override("claude/sonnet", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_known_bare_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "gpt-5.5"}},
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_alias_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {"claude": "fast-worker"},
            "model_aliases": {"fast-worker": "codex/gpt-5.5"},
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_exact_key_beats_bare_model_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "claude/sonnet",
                "opus": "gemini/gemini-2.5-pro",
                "claude/opus": "codex/gpt-5.5",
            },
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_bare_model_key_beats_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "opus": "codex/gpt-5.5",
            },
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_provider_key_does_not_cross_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "codex",
            "worker_models": {"claude": "gemini/gemini-2.5-pro"},
        },
    )

    assert resolve_effective_worker_provider_model() == (
        resolve_effective_default_provider_model()
    )


def test_resolve_effective_worker_primary_override_selects_mapping_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "codex": "claude/sonnet",
            },
        },
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("claude", "sonnet")


def test_resolve_effective_worker_unknown_config_model_uses_config_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"codex": "custom-worker-model"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("claude", "custom-worker-model")


def test_resolve_effective_worker_falls_through_to_primary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "o3")


def test_resolve_effective_worker_without_worker_state_matches_primary_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_effective_worker_provider_model() == (
        resolve_effective_default_provider_model()
    )


def test_resolve_effective_worker_self_reference_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"codex": "worker"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "o3")


def test_resolve_effective_worker_responds_to_primary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The effective worker helper still follows primary temporary overrides."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "codex": "claude/sonnet",
            },
        },
    )
    # No override -> matches the configured-default primary (claude) -> gemini.
    assert resolve_effective_worker_provider_model() == ("gemini", "gemini-2.5-pro")

    # Primary override to codex/o3 -> worker mapping now keys off codex -> sonnet.
    set_temporary_override("codex/o3", 3600.0, source="ace")
    assert resolve_effective_worker_provider_model() == ("claude", "sonnet")


# ---------------------------------------------------------------------------
# resolve_worker_provider_model_for_primary
# ---------------------------------------------------------------------------


def test_resolve_worker_for_primary_exact_key_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact ``provider/model`` key beats bare-model and provider keys."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "claude/sonnet",
                "opus": "gemini/gemini-2.5-pro",
                "claude/opus": "codex/gpt-5.5",
            },
        },
    )

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")
    assert (resolution.provider, resolution.model) == ("codex", "gpt-5.5")
    assert resolution.source == "config"
    assert resolution.matched_key == "claude/opus"
    assert resolution.configured_target == "codex/gpt-5.5"
    assert (resolution.primary_provider, resolution.primary_model) == ("claude", "opus")


def test_resolve_worker_for_primary_bare_model_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare-model key matches when no exact ``provider/model`` key exists."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "opus": "codex/gpt-5.5",
            },
        },
    )

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")
    assert (resolution.provider, resolution.model) == ("codex", "gpt-5.5")
    assert resolution.matched_key == "opus"


def test_resolve_worker_for_primary_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider key matches the supplied primary provider."""
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"codex": "claude/opus"}},
    )

    resolution = resolve_worker_provider_model_for_primary("codex", "o3")
    assert (resolution.provider, resolution.model) == ("claude", "opus")
    assert resolution.source == "config"
    assert resolution.matched_key == "codex"


def test_resolve_worker_for_primary_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active worker override wins over a matching config entry."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {"claude/opus": "gemini/gemini-2.5-pro"},
        },
    )
    set_temporary_override("codex/gpt-5.5", 3600.0, source="ace", role="worker")

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")
    assert (resolution.provider, resolution.model) == ("codex", "gpt-5.5")
    assert resolution.source == "override"
    assert resolution.matched_key is None


def test_resolve_worker_for_primary_falls_back_to_supplied_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No override or config match returns the supplied primary lane."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")
    assert (resolution.provider, resolution.model) == ("claude", "opus")
    assert resolution.source == "primary"
    assert resolution.matched_key is None
    assert resolution.configured_target is None


def test_resolve_worker_for_primary_uses_supplied_lane_not_effective_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supplied primary lane drives the lookup, not the global default.

    A primary override is active (codex/o3), but the contextual resolver is
    asked about a *different* planner lane (claude/opus) and must key off that.
    """
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "codex": "gemini/gemini-2.5-pro",
                "claude/opus": "codex/gpt-5.5",
            },
        },
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    resolution = resolve_worker_provider_model_for_primary("claude", "opus")
    assert (resolution.provider, resolution.model) == ("codex", "gpt-5.5")
    assert resolution.matched_key == "claude/opus"
