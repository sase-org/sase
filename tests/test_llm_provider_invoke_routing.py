"""Tests for invoke_agent model-alias, pool, and default-model routing.

Call-site success/error orchestration lives in
``test_llm_provider_invoke.py``; env and compatibility overrides live in
``test_llm_provider_invoke_overrides.py``.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions
from sase.xprompt.directives import PromptDirectives
from tests._llm_provider_invoke_helpers import (
    _NO_EFFORT,
    _assert_get_provider_called_once,
    _assert_routing_context_kw,
    _clear_execution_provider_override,  # noqa: F401 (registers the autouse fixture)
)


@patch("sase.llm_provider.config.get_llm_provider_config")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_resolves_model_alias_for_provider_and_model(
    mock_postprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_config: MagicMock,
) -> None:
    """A %model alias selects the resolved provider and provider-local model."""
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
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    invoke_agent(
        "prompt",
        agent_type="test",
        suppress_output=True,
        skip_preprocessing=True,
        directives=PromptDirectives(model="other"),
    )

    _assert_get_provider_called_once(mock_get_provider, "claude")
    mock_provider.invoke.assert_called_once_with(
        "prompt",
        model_tier="large",
        suppress_output=True,
        model_override="opus",
        options=_NO_EFFORT,
    )


def test_invoke_agent_consumes_pool_once_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider-less %model lane advances exactly once for each call."""
    from sase.llm_provider import config as llm_config

    config = {
        "provider": "claude",
        "model_aliases": {
            "custom": {
                "pool": {
                    "model": "claude/opus@medium | codex/gpt-5.5",
                    "description": "Test pool.",
                }
            }
        },
    }
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(
        llm_config, "_resolved_target_is_available", lambda _target: True
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        for _ in range(2):
            invoke_agent(
                "prompt",
                agent_type="test",
                suppress_output=True,
                skip_preprocessing=True,
                directives=PromptDirectives(model="@pool"),
            )

    assert provider.invoke.call_args_list[0].kwargs == {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": "opus",
        "options": LLMInvocationOptions(reasoning_effort="medium", explicit=False),
    }
    assert provider.invoke.call_args_list[1].kwargs == {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": "gpt-5.5",
        "options": _NO_EFFORT,
    }


def test_invoke_agent_warns_when_model_override_falls_back_to_default_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unresolved %model override logs the default-provider fallback."""
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")

    with (
        patch(
            "sase.llm_provider.registry.resolve_model_provider_with_cursor",
            return_value=(None, "unregistered-model", None, (), None),
        ) as mock_resolve,
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="codex",
        ) as mock_default_provider,
        patch(
            "sase.llm_provider._invoke.get_provider",
            return_value=mock_provider,
        ) as mock_get_provider,
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
        caplog.at_level(logging.WARNING, logger="sase.llm_provider.launch_selection"),
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            suppress_output=True,
            skip_preprocessing=True,
            directives=PromptDirectives(model="unregistered-model"),
        )

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args == ("unregistered-model", None)
    assert mock_resolve.call_args.kwargs["consume"] is True
    assert mock_resolve.call_args.kwargs["model_tier"] == "large"
    context = _assert_routing_context_kw(mock_resolve.call_args.kwargs)
    mock_default_provider.assert_called_once_with(routing_context=context)
    _assert_get_provider_called_once(mock_get_provider, "codex")
    mock_provider.invoke.assert_called_once_with(
        "prompt",
        model_tier="large",
        suppress_output=True,
        model_override="unregistered-model",
        options=_NO_EFFORT,
    )
    assert "unregistered-model" in caplog.text
    assert "codex" in caplog.text


@patch("sase.llm_provider.registry.get_llm_provider_config")
@patch("sase.llm_provider.config.get_llm_provider_config")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_no_directive_routes_through_configured_default_model(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_config: MagicMock,
    mock_registry_config: MagicMock,
) -> None:
    """A no-%model launch routes through ``llm_provider.default_model``."""
    cfg = {
        "provider": "claude",
        "default_model": "codex/gpt-5.6-sol",
    }
    mock_config.return_value = cfg
    mock_registry_config.return_value = cfg
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    invoke_agent("prompt", agent_type="test", suppress_output=True)

    _assert_get_provider_called_once(mock_get_provider, "codex")
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override="gpt-5.6-sol",
        options=_NO_EFFORT,
    )


def test_invoke_agent_no_directive_routes_through_shipped_default_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invoke default branch consumes the shipped ``@large`` pool."""
    from sase.llm_provider import config as llm_config
    from sase.llm_provider.model_alias_policy import LARGE_MODEL_ALIAS_NAME
    from tests._model_alias_defaults_fixture import (
        frozen_selector_provider_model_effort,
    )

    config = {"provider": "claude"}
    monkeypatch.setattr(llm_config, "get_llm_provider_config", lambda: config)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: config
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    llm_config._get_model_aliases_for_token.cache_clear()

    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        for _ in range(2):
            invoke_agent(
                "prompt",
                agent_type="test",
                suppress_output=True,
                skip_preprocessing=True,
                directives=PromptDirectives(),
            )

    _first_provider, first_model, first_effort = frozen_selector_provider_model_effort(
        LARGE_MODEL_ALIAS_NAME, 0
    )
    _second_provider, second_model, second_effort = (
        frozen_selector_provider_model_effort(LARGE_MODEL_ALIAS_NAME, 1)
    )
    assert provider.invoke.call_args_list[0].kwargs == {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": first_model,
        "options": LLMInvocationOptions(
            reasoning_effort=first_effort,
            explicit=False,
        ),
    }
    assert provider.invoke.call_args_list[1].kwargs == {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": second_model,
        "options": LLMInvocationOptions(
            reasoning_effort=second_effort,
            explicit=False,
        ),
    }
