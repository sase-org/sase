"""Tests for llm_provider types, base class, and registry."""

from unittest.mock import MagicMock, patch

import pytest
from sase.llm_provider._plugin_manager import LLMPluginManager
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.registry import (
    get_provider,
    model_short_alias_map,
    resolve_model_provider,
)
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


def test_get_provider_unknown_raises() -> None:
    """Test that requesting an unknown provider raises KeyError."""
    with pytest.raises(KeyError, match="Unknown LLM provider"):
        get_provider("nonexistent_provider_xyz")


@patch("sase.llm_provider.registry.shutil.which", return_value=None)
@patch("sase.llm_provider.registry.get_llm_provider_config", return_value={})
def test_get_default_provider_errors_without_detectable_cli(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """No default provider is selected when no provider CLI is on PATH."""
    with pytest.raises(RuntimeError, match="No LLM provider is available"):
        get_provider()


@patch("sase.llm_provider.registry.shutil.which", return_value="/usr/bin/claude")
@patch(
    "sase.llm_provider.registry.get_llm_provider_config",
    return_value={"provider": "agy"},
)
def test_config_provider_overrides_auto_detection(
    mock_config: MagicMock,
    mock_which: MagicMock,
) -> None:
    """Test that explicit config overrides auto-detection."""
    provider = get_provider()
    assert isinstance(provider, LLMPluginManager)
    assert provider.provider_name() == "agy"
    mock_which.assert_not_called()


# --- resolve_model_provider tests ---


def test_resolve_model_provider_explicit_syntax() -> None:
    """Explicit provider/model syntax resolves correctly."""
    assert resolve_model_provider("codex/o3") == ("codex", "o3")
    assert resolve_model_provider("claude/opus") == ("claude", "opus")
    assert resolve_model_provider("claude/claude-opus-5") == (
        "claude",
        "claude-opus-5",
    )
    assert resolve_model_provider("claude/claude-sonnet-5") == (
        "claude",
        "claude-sonnet-5",
    )
    assert resolve_model_provider("agy/gemini-3.6-flash-high") == (
        "agy",
        "gemini-3.6-flash-high",
    )


def test_resolve_model_provider_implicit_mapping() -> None:
    """Known model names resolve to the correct provider."""
    assert resolve_model_provider("o3") == ("codex", "o3")
    assert resolve_model_provider("opus") == ("claude", "opus")
    assert resolve_model_provider("sonnet") == ("claude", "sonnet")
    assert resolve_model_provider("claude-opus-5") == (None, "claude-opus-5")
    assert resolve_model_provider("claude-sonnet-5") == (None, "claude-sonnet-5")
    assert resolve_model_provider("claude-haiku-4-5") == (
        "claude",
        "claude-haiku-4-5",
    )
    assert resolve_model_provider("claude-fable-5") == (
        "claude",
        "claude-fable-5",
    )
    assert resolve_model_provider("gpt-5.3-codex-spark") == (
        "codex",
        "gpt-5.3-codex-spark",
    )
    assert resolve_model_provider("gpt-5.6-sol") == ("codex", "gpt-5.6-sol")
    assert resolve_model_provider("gpt-5.5") == ("codex", "gpt-5.5")
    assert resolve_model_provider("gpt-5.3-codex") == ("codex", "gpt-5.3-codex")
    assert resolve_model_provider("gemini-3.6-flash-high") == (
        "agy",
        "gemini-3.6-flash-high",
    )
    assert resolve_model_provider("qwen3.6-plus") == ("qwen", "qwen3.6-plus")


def test_resolve_model_provider_unknown_model() -> None:
    """Unknown model names return None provider (falls back to default)."""
    assert resolve_model_provider("custom-model") == (None, "custom-model")
    assert resolve_model_provider("my-fine-tune") == (None, "my-fine-tune")


def test_resolve_model_provider_explicit_with_unknown_model() -> None:
    """Explicit syntax works with any model name, even unknown ones."""
    assert resolve_model_provider("codex/my-fine-tune") == ("codex", "my-fine-tune")
    assert resolve_model_provider("claude/custom-v2") == ("claude", "custom-v2")


# --- model_short_alias_map tests ---


def test_model_short_alias_map_contains_agy_entries() -> None:
    """The aggregated alias map carries the agy plugin's entries."""
    aliases = model_short_alias_map()
    assert aliases.get("gemini-3.6-flash-high") == "flash36h"
    assert aliases.get("gemini-3.6-flash-low") == "flash36l"
    assert aliases.get("gemini-3.5-flash-high") == "flash35h"
    assert aliases.get("gemini-3.1-pro-high") == "pro31h"


def test_model_short_alias_map_contains_codex_entries() -> None:
    """The aggregated alias map carries the codex plugin's entries."""
    aliases = model_short_alias_map()
    assert aliases.get("codex-mini-latest") == "mini"
    assert aliases.get("gpt-5.6-sol") == "gpt56sol"
    assert aliases.get("gpt-5.5") == "gpt55"


def test_model_short_alias_map_contains_claude_entries() -> None:
    """The aggregated alias map carries the claude plugin's entries."""
    aliases = model_short_alias_map()
    assert "claude-opus-5" not in aliases
    assert "claude-sonnet-5" not in aliases
    assert aliases.get("claude-haiku-4-5") == "haiku45"
    assert aliases.get("claude-fable-5") == "fable"


def test_model_short_alias_map_contains_spark_entry() -> None:
    """Codex Spark has a dedicated builtin short alias."""
    aliases = model_short_alias_map()
    assert aliases.get("gpt-5.3-codex-spark") == "gpt53spark"


def test_model_short_alias_map_omits_short_models() -> None:
    """Already-short model names (opus/sonnet/o3/gpt-4o) carry no alias."""
    aliases = model_short_alias_map()
    assert "opus" not in aliases
    assert "sonnet" not in aliases
    assert "haiku" not in aliases
    assert "o3" not in aliases
    assert "gpt-4o" not in aliases
