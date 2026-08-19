"""Routing semantics for temporarily disabled LLM providers."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.alias_view import build_alias_views
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.registry import (
    LLM_EXEC_PROVIDER_ENV,
    ProviderTemporarilyDisabledError,
    build_provider_routing_statuses,
    get_configured_default_provider_name,
    get_provider,
    resolve_execution_provider_name,
    resolve_model_provider_with_effort,
)
from sase.llm_provider.temporary_override import (
    resolve_effective_default_provider_model_with_effort,
    set_temporary_override,
)
from sase.llm_provider.temporary_override_state import TemporaryLLMOverride
from sase.xprompt import model_completion
from tests._xprompt_model_completion_helpers import metadata_payload
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _disable(
    provider: str,
    *,
    expires_at: float | None = None,
    mode: str = "hard",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source="test",
        mode=mode,
    )


def _override(
    provider: str, model: str, *, effort: str | None = None
) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=None,
        source="test",
        effort=effort,
    )


def _pin_cli_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available",
        lambda _provider: True,
    )


def test_round_robin_skips_disabled_member_and_restores_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_cli_available(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus | codex/gpt-5.5",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )

    disables = {"claude": _disable("claude")}

    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("codex", "gpt-5.5", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("codex", "gpt-5.5", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables={},
    ) == ("claude", "opus", None)


def test_all_disabled_pool_retains_member_zero_without_cursor_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_cli_available(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus | codex/gpt-5.5",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    disables = {"claude": _disable("claude"), "codex": _disable("codex")}

    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables={},
    ) == ("claude", "opus", None)


def test_ordered_fallback_skips_disabled_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_cli_available(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fallback": {
                        "model": "claude/opus@high || codex/gpt-5.6-sol@medium",
                        "description": "Test fallback.",
                    }
                }
            },
        },
    )

    assert resolve_model_provider_with_effort(
        "@fallback",
        provider_disables={"claude": _disable("claude")},
    ) == ("codex", "gpt-5.6-sol", "medium")
    assert resolve_model_provider_with_effort("@fallback", provider_disables={}) == (
        "claude",
        "opus",
        "high",
    )


def test_alias_override_pauses_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_cli_available(monkeypatch)
    override = _override("claude", "opus")
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"medium": "claude/sonnet || codex/gpt-5.6-sol"}
            },
        },
    )
    monkeypatch.setattr(
        llm_config,
        "_active_alias_overrides",
        lambda: {"medium": override},
    )
    disables = {"claude": _disable("claude")}

    assert resolve_model_provider_with_effort(
        "@medium",
        provider_disables=disables,
    ) == ("codex", "gpt-5.6-sol", None)
    assert resolve_model_provider_with_effort(
        "@medium",
        provider_disables={},
    ) == ("claude", "opus", None)

    view = next(
        view
        for view in build_alias_views(
            overrides={"medium": override},
            provider_disables=disables,
        )
        if view.name == "medium"
    )
    assert view.override is override
    assert view.is_override_paused
    assert (view.provider, view.model) == ("codex", "gpt-5.6-sol")


def test_default_override_pauses_for_disabled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_cli_available(monkeypatch)
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_model": "claude/sonnet@high || codex/gpt-5.6-sol@medium",
        },
    )
    set_temporary_override("claude/opus@high", None, source="test")

    assert resolve_effective_default_provider_model_with_effort(
        provider_disables={"claude": _disable("claude")}
    ) == ("codex", "gpt-5.6-sol", "medium")
    assert resolve_effective_default_provider_model_with_effort(
        provider_disables={}
    ) == ("claude", "opus", "high")


def test_dispatch_gate_blocks_disabled_provider_before_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_provider = Mock(side_effect=AssertionError("provider was created"))
    monkeypatch.setattr("sase.llm_provider.registry.create_provider", create_provider)

    with pytest.raises(
        ProviderTemporarilyDisabledError,
        match="LLM provider 'claude' is temporarily disabled until cleared",
    ):
        get_provider("claude", provider_disables={"claude": _disable("claude")})

    create_provider.assert_not_called()


def test_execution_provider_env_override_uses_dispatch_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LLM_EXEC_PROVIDER_ENV, "claude")
    execution_provider = resolve_execution_provider_name(
        "codex",
        provider_disables={"claude": _disable("claude")},
    )

    assert execution_provider == "claude"
    with pytest.raises(ProviderTemporarilyDisabledError):
        get_provider(
            execution_provider, provider_disables={"claude": _disable("claude")}
        )


def test_autodetection_skips_disabled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = metadata_payload()
    payload["provider_names"] = ["claude", "codex"]
    monkeypatch.setattr(
        "sase.llm_provider.registry._llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {},
    )
    _pin_cli_available(monkeypatch)

    assert (
        get_configured_default_provider_name(
            provider_disables={"claude": _disable("claude")}
        )
        == "codex"
    )


def test_model_completion_omits_disabled_concrete_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    static_values = {
        entry.value
        for entry in model_completion.build_model_completion_catalog(
            provider_disables={}
        )
    }
    disabled_values = {
        entry.value
        for entry in model_completion.build_model_completion_catalog(
            provider_disables={"claude": _disable("claude")}
        )
    }

    assert "opus" in static_values
    assert "claude/" in static_values
    assert "opus" not in disabled_values
    assert "claude/" not in disabled_values
    assert "gpt-5.6-sol" in disabled_values


def test_model_completion_keeps_soft_disabled_concrete_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_completion, "get_llm_metadata_payload", metadata_payload)
    monkeypatch.setattr(model_completion, "get_model_aliases", lambda: {})
    monkeypatch.setattr(model_completion, "build_alias_views", lambda **_kwargs: [])

    entries = model_completion.build_model_completion_catalog(
        provider_disables={
            "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)
        }
    )
    by_value = {entry.value: entry for entry in entries}

    assert "opus" in by_value
    assert "claude/" in by_value
    assert by_value["opus"].provenance == "soft"
    assert by_value["claude/"].provenance == "soft"
    assert by_value["gpt-5.6-sol"].provenance != "soft"


def test_provider_routing_statuses_include_disable_and_affected_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = metadata_payload()
    payload["provider_names"] = ["claude", "codex"]
    monkeypatch.setattr(
        "sase.llm_provider.registry._llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry._affected_aliases_by_provider",
        lambda: {"claude": ("default",)},
    )
    _pin_cli_available(monkeypatch)

    rows = {
        row.provider: row
        for row in build_provider_routing_statuses(
            provider_disables={"claude": _disable("claude")}
        )
    }

    assert rows["claude"].active_disable is not None
    assert rows["claude"].model_count == 3
    assert rows["claude"].affected_aliases == ("default",)
    assert rows["codex"].active_disable is None
