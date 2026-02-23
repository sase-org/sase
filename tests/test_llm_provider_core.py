"""Tests for llm_provider types, base class, and registry."""

from unittest.mock import MagicMock, patch

import pytest
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.gemini import GeminiProvider
from sase.llm_provider.registry import _REGISTRY, get_provider, register_provider
from sase.llm_provider.types import _MODEL_SIZE_TO_TIER, LoggingContext, ModelTier


# --- types.py tests ---


def test_model_size_to_tier_mapping() -> None:
    """Test the model_size to model_tier mapping."""
    assert _MODEL_SIZE_TO_TIER["big"] == "large"
    assert _MODEL_SIZE_TO_TIER["little"] == "small"


def test_model_tier_type() -> None:
    """Test ModelTier type accepts valid values."""
    tier_large: ModelTier = "large"
    tier_small: ModelTier = "small"
    assert tier_large == "large"
    assert tier_small == "small"


def test_logging_context_defaults() -> None:
    """Test LoggingContext dataclass default values."""
    ctx = LoggingContext()
    assert ctx.agent_type == "agent"
    assert ctx.iteration is None
    assert ctx.workflow_tag is None
    assert ctx.artifacts_dir is None
    assert ctx.suppress_output is False
    assert ctx.workflow is None
    assert ctx.timestamp is None
    assert ctx.is_home_mode is False
    assert ctx.decision_counts is None


def test_logging_context_custom_values() -> None:
    """Test LoggingContext dataclass with custom values."""
    ctx = LoggingContext(
        agent_type="editor",
        iteration=3,
        workflow_tag="test-tag",
        artifacts_dir="/tmp/test",
        suppress_output=True,
        workflow="crs",
        timestamp="260214_120000",
        is_home_mode=True,
        decision_counts={"yes": 5, "no": 2},
    )
    assert ctx.agent_type == "editor"
    assert ctx.iteration == 3
    assert ctx.workflow_tag == "test-tag"
    assert ctx.artifacts_dir == "/tmp/test"
    assert ctx.suppress_output is True
    assert ctx.workflow == "crs"
    assert ctx.timestamp == "260214_120000"
    assert ctx.is_home_mode is True
    assert ctx.decision_counts == {"yes": 5, "no": 2}


# --- base.py tests ---


def test_llm_provider_is_abstract() -> None:
    """Test that LLMProvider cannot be instantiated directly."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_llm_provider_subclass() -> None:
    """Test that a concrete subclass can be created."""

    class MockProvider(LLMProvider):
        def invoke(
            self,
            prompt: str,
            *,
            model_tier: ModelTier,
            suppress_output: bool = False,
            model_override: str | None = None,
        ) -> str:
            return f"mock response to: {prompt}"

    provider = MockProvider()
    result = provider.invoke("hello", model_tier="large")
    assert result == "mock response to: hello"


# --- registry.py tests ---


def test_register_and_get_provider() -> None:
    """Test registering and retrieving a provider."""

    class TestProvider(LLMProvider):
        def invoke(
            self,
            prompt: str,
            *,
            model_tier: ModelTier,
            suppress_output: bool = False,
            model_override: str | None = None,
        ) -> str:
            return "test"

    register_provider("test_provider", TestProvider)
    try:
        provider = get_provider("test_provider")
        assert isinstance(provider, TestProvider)
    finally:
        # Clean up
        _REGISTRY.pop("test_provider", None)


def test_get_provider_unknown_raises() -> None:
    """Test that requesting an unknown provider raises KeyError."""
    with pytest.raises(KeyError, match="Unknown LLM provider"):
        get_provider("nonexistent_provider_xyz")


@patch("sase.llm_provider.registry.shutil.which", return_value=None)
def test_get_default_provider_falls_back_to_gemini(mock_which: MagicMock) -> None:
    """Test that the default provider is 'gemini' when claude is not on PATH."""
    provider = get_provider()
    assert isinstance(provider, GeminiProvider)


@patch("sase.llm_provider.registry.shutil.which", return_value="/usr/bin/claude")
@patch(
    "sase.llm_provider.registry.get_llm_provider_config",
    return_value={"provider": "gemini"},
)
def test_config_provider_overrides_auto_detection(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that explicit config overrides auto-detection."""
    provider = get_provider()
    assert isinstance(provider, GeminiProvider)
    mock_which.assert_not_called()
