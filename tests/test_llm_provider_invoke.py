"""Tests for llm_provider invoke_agent orchestration."""

import os
from unittest.mock import MagicMock, patch

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import _PreprocessResult


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.print_prompt_and_response")
@patch("sase.llm_provider._invoke.print_decision_counts")
@patch("sase.llm_provider._invoke.postprocess_success")
def test_invoke_agent_with_mocked_provider(
    mock_postprocess: MagicMock,
    mock_print_counts: MagicMock,
    mock_print_prompt: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test invoke_agent with a mocked provider."""
    # Set up mocks
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = "mock response"
    mock_get_provider.return_value = mock_provider

    # Call invoke_agent
    result = invoke_agent(
        "raw prompt",
        agent_type="test",
        model_tier="large",
        suppress_output=True,
    )

    # Verify preprocessing was called
    mock_preprocess.assert_called_once_with("raw prompt", is_home_mode=False)

    # Verify provider was called
    mock_provider.invoke.assert_called_once_with(
        "preprocessed prompt",
        model_tier="large",
        suppress_output=True,
        model_override=None,
    )

    # Verify result
    assert result.content == "mock response"


@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_handles_error(
    mock_postprocess_error: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
) -> None:
    """Test invoke_agent handles provider errors gracefully."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.side_effect = Exception("test error")
    mock_get_provider.return_value = mock_provider

    result = invoke_agent(
        "raw prompt",
        agent_type="test",
        suppress_output=True,
    )

    assert "Error: test error" in result.content
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
    mock_provider.invoke.return_value = "response"
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
    mock_provider.invoke.return_value = "response"
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
    mock_provider.invoke.return_value = "response"
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
