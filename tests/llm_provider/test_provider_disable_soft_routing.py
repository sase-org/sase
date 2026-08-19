"""Routing semantics for soft-disabled LLM providers.

Mirrors :mod:`tests.llm_provider.test_provider_disable_routing`'s hard-disable
coverage, but exercises the mode-aware selection policy added alongside soft
disables: a soft disable spares a ``|`` pool member while a preferred member
can cover, never diverts a ``||`` fallback chain, and never fails a launch
outright (routing, dispatch, autodetect, and temporary overrides all stay
available on a soft-disabled provider).
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.alias_view import build_alias_views
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.registry import (
    ProviderTemporarilyDisabledError,
    get_configured_default_provider_name,
    get_provider,
    resolve_model_provider_with_effort,
)
from sase.llm_provider.temporary_override_state import TemporaryLLMOverride
from tests._xprompt_model_completion_helpers import metadata_payload
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _disable(
    provider: str,
    *,
    mode: str = PROVIDER_DISABLE_MODE_HARD,
    expires_at: float | None = None,
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


def test_pool_spares_soft_member_while_preferred_available_and_cursor_advances(
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
                        "model": "claude/opus | codex/gpt-5.5 | grok/grok-4.6",
                        "description": "Test pool.",
                    }
                }
            },
        },
    )
    disables = {"codex": _disable("codex", mode=PROVIDER_DISABLE_MODE_SOFT)}

    # claude (index 0) is preferred and wins first; the cursor advances past
    # it to index 1 (codex), which is spared, so grok (index 2) wins next.
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("grok", "grok-4.6", None)
    # The cursor wrapped back to index 0; codex is still spared.
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)


def test_pool_rotates_normally_when_every_member_is_soft(
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
    disables = {
        "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT),
        "codex": _disable("codex", mode=PROVIDER_DISABLE_MODE_SOFT),
    }

    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("codex", "gpt-5.5", None)
    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)


def test_pool_selects_soft_member_over_cli_missing_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cli_available(provider: str) -> bool:
        return provider != "codex"

    monkeypatch.setattr(
        "sase.llm_provider.registry._provider_cli_available", cli_available
    )
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
    # claude is soft-disabled (SPARING); codex has no CLI (UNAVAILABLE). With
    # no PREFERRED member, sparing members rotate in — so claude wins, never
    # the CLI-missing member.
    disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}

    assert resolve_model_provider_with_effort(
        "@pool",
        consume=True,
        provider_disables=disables,
    ) == ("claude", "opus", None)


def test_fallback_soft_first_candidate_is_not_diverted_unlike_hard(
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
    soft_disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}
    hard_disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_HARD)}

    assert resolve_model_provider_with_effort(
        "@fallback",
        provider_disables=soft_disables,
    ) == ("claude", "opus", "high")
    assert resolve_model_provider_with_effort(
        "@fallback",
        provider_disables=hard_disables,
    ) == ("codex", "gpt-5.6-sol", "medium")


def test_get_provider_soft_disable_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = Mock()
    create_provider = Mock(return_value=sentinel)
    monkeypatch.setattr("sase.llm_provider.registry.create_provider", create_provider)

    result = get_provider(
        "claude",
        provider_disables={
            "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)
        },
    )

    assert result is sentinel
    create_provider.assert_called_once_with("claude")


def test_get_provider_hard_disable_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_provider = Mock(side_effect=AssertionError("provider was created"))
    monkeypatch.setattr("sase.llm_provider.registry.create_provider", create_provider)

    with pytest.raises(ProviderTemporarilyDisabledError):
        get_provider(
            "claude",
            provider_disables={
                "claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_HARD)
            },
        )

    create_provider.assert_not_called()


def test_autodetection_prefers_preferred_candidate_over_soft(
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

    disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}

    assert get_configured_default_provider_name(provider_disables=disables) == "codex"


def test_autodetection_falls_back_to_soft_only_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = metadata_payload()
    payload["provider_names"] = ["claude"]
    monkeypatch.setattr(
        "sase.llm_provider.registry._llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {},
    )
    _pin_cli_available(monkeypatch)

    disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}

    assert get_configured_default_provider_name(provider_disables=disables) == "claude"


def test_alias_override_stays_applied_for_soft_but_suspends_for_hard(
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
    soft_disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)}
    hard_disables = {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_HARD)}

    assert resolve_model_provider_with_effort(
        "@medium",
        provider_disables=soft_disables,
    ) == ("claude", "opus", None)
    assert resolve_model_provider_with_effort(
        "@medium",
        provider_disables=hard_disables,
    ) == ("codex", "gpt-5.6-sol", None)

    soft_view = next(
        view
        for view in build_alias_views(
            overrides={"medium": override},
            provider_disables=soft_disables,
        )
        if view.name == "medium"
    )
    assert soft_view.override is override
    assert not soft_view.is_override_paused
    assert (soft_view.provider, soft_view.model) == ("claude", "opus")

    hard_view = next(
        view
        for view in build_alias_views(
            overrides={"medium": override},
            provider_disables=hard_disables,
        )
        if view.name == "medium"
    )
    assert hard_view.is_override_paused
    assert (hard_view.provider, hard_view.model) == ("codex", "gpt-5.6-sol")
