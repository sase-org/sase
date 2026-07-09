"""Tests for llm_provider invoke_agent orchestration."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.types import (
    InvokeResult,
    LLMInvocationError,
    LLMInvocationOptions,
)
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.xprompt.directives import PromptDirectives

_NO_EFFORT = LLMInvocationOptions(reasoning_effort=None, explicit=False)


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_handles_error(
    mock_postprocess_error: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test invoke_agent raises LLMInvocationError on provider failure."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.side_effect = Exception("test error")
    mock_get_provider.return_value = mock_provider

    with pytest.raises(LLMInvocationError, match="Error: test error"):
        invoke_agent(
            "raw prompt",
            agent_type="test",
            suppress_output=True,
        )

    mock_postprocess_error.assert_called_once()


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.print_prompt_and_response")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_model_size_backward_compat(
    mock_postprocess: MagicMock,
    mock_print_prompt: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test invoke_agent with deprecated model_size parameter."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    invoke_agent(
        "prompt",
        agent_type="test",
        model_size="little",
        suppress_output=True,
    )

    # Should have converted "little" to "small"
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="small",
        suppress_output=True,
        model_override=None,
        options=_NO_EFFORT,
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_returns_local_ai_message_with_content(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """invoke_agent returns the SASE-native AIMessage carrying provider content."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="provider response")
    mock_get_provider.return_value = mock_provider

    result = invoke_agent(
        "prompt",
        agent_type="test",
        suppress_output=True,
    )

    assert isinstance(result, AIMessage)
    assert result.content == "provider response"


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_model_tier_override_env(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test that SASE_MODEL_TIER_OVERRIDE env var overrides model_tier."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    os.environ["SASE_MODEL_TIER_OVERRIDE"] = "small"
    try:
        invoke_agent(
            "prompt",
            agent_type="test",
            model_tier="large",  # Should be overridden to "small"
            suppress_output=True,
        )

        mock_provider.invoke.assert_called_once_with(
            "preprocessed",
            model_tier="small",
            suppress_output=True,
            model_override=None,
            options=_NO_EFFORT,
        )
    finally:
        del os.environ["SASE_MODEL_TIER_OVERRIDE"]


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

    mock_get_provider.assert_called_once_with("claude")
    mock_provider.invoke.assert_called_once_with(
        "prompt",
        model_tier="large",
        suppress_output=True,
        model_override="opus",
        options=_NO_EFFORT,
    )


def test_invoke_agent_warns_when_model_override_falls_back_to_default_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unresolved %model override logs the default-provider fallback."""
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")

    with (
        patch(
            "sase.llm_provider._invoke.resolve_model_provider",
            return_value=(None, "unregistered-model"),
        ) as mock_resolve,
        patch(
            "sase.llm_provider._invoke.get_default_provider_name",
            return_value="codex",
        ) as mock_default_provider,
        patch(
            "sase.llm_provider._invoke.get_provider",
            return_value=mock_provider,
        ) as mock_get_provider,
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.llm_provider._invoke.run_commit_finalizer",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
        caplog.at_level(logging.WARNING, logger="sase.llm_provider._invoke"),
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            suppress_output=True,
            skip_preprocessing=True,
            directives=PromptDirectives(model="unregistered-model"),
        )

    mock_resolve.assert_called_once_with("unregistered-model")
    mock_default_provider.assert_called_once_with()
    mock_get_provider.assert_called_once_with("codex")
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
def test_invoke_agent_no_directive_routes_through_configured_default_alias(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_config: MagicMock,
    mock_registry_config: MagicMock,
) -> None:
    """A no-%model launch routes through a configured ``@default`` alias.

    With ``model_aliases.builtin.default`` set, the no-directive launch must
    select the configured default's provider/model instead of silently falling
    back to the autodetected provider's tier default (epic sase-5d phase 1 exit
    criterion).
    """
    cfg = {
        "provider": "claude",
        "model_aliases": {"builtin": {"default": "codex/gpt-5.6"}},
    }
    mock_config.return_value = cfg
    mock_registry_config.return_value = cfg
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    invoke_agent("prompt", agent_type="test", suppress_output=True)

    mock_get_provider.assert_called_once_with("codex")
    mock_provider.invoke.assert_called_once_with(
        "preprocessed",
        model_tier="large",
        suppress_output=True,
        model_override="gpt-5.6",
        options=_NO_EFFORT,
    )


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_model_size_override_env_compat(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test that SASE_MODEL_SIZE_OVERRIDE env var still works."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="response")
    mock_get_provider.return_value = mock_provider

    os.environ["SASE_MODEL_SIZE_OVERRIDE"] = "little"
    try:
        invoke_agent(
            "prompt",
            agent_type="test",
            model_tier="large",  # Should be overridden to "small" via "little"
            suppress_output=True,
        )

        mock_provider.invoke.assert_called_once_with(
            "preprocessed",
            model_tier="small",
            suppress_output=True,
            model_override=None,
            options=_NO_EFFORT,
        )
    finally:
        del os.environ["SASE_MODEL_SIZE_OVERRIDE"]
