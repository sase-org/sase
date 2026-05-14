"""Tests for llm_provider invoke_agent orchestration."""

import os
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.types import InvokeResult, LLMInvocationError
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.xprompt.directives import PromptDirectives


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
    )


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
    mock_config.return_value = {"model_aliases": {"other": "claude/opus"}}
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
    )


@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_daemon_scheduler_invoke_routes_provider_call_through_host(
    mock_postprocess: MagicMock,
    mock_preprocess: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    calls: list[dict[str, object]] = []

    def fake_invoke_provider_via_host(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "content": "hosted",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }

    monkeypatch.setattr(
        "sase.llm_provider._invoke._should_route_llm_invoke_through_host",
        lambda: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider._invoke._invoke_provider_via_host",
        fake_invoke_provider_via_host,
    )

    response = invoke_agent("prompt", agent_type="test", suppress_output=True)

    assert response.content == "hosted"
    assert calls[0]["prompt"] == "preprocessed"
    assert calls[0]["model_tier"] == "large"
    assert calls[0]["suppress_output"] is True
    mock_postprocess.assert_called_once()


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
        )
    finally:
        del os.environ["SASE_MODEL_SIZE_OVERRIDE"]
