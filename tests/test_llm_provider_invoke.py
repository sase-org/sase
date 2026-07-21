"""Tests for llm_provider invoke_agent orchestration."""

import json
import logging
import os
from pathlib import Path
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


@pytest.fixture(autouse=True)
def _clear_execution_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_LLM_EXEC_PROVIDER", raising=False)


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


def test_invoke_agent_execution_provider_override_preserves_requested_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "claude", "model": "opus"}),
        encoding="utf-8",
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")
    monkeypatch.setenv("SASE_LLM_EXEC_PROVIDER", "fakey")

    with (
        patch(
            "sase.llm_provider._invoke.get_provider", return_value=provider
        ) as get_provider,
        patch("sase.llm_provider._invoke.postprocess_success"),
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            artifacts_dir=str(artifacts),
            provider_name="claude",
            suppress_output=True,
            skip_preprocessing=True,
            directives=PromptDirectives(model="opus"),
        )

    get_provider.assert_called_once_with("fakey")
    provider.invoke.assert_called_once_with(
        "prompt",
        model_tier="large",
        suppress_output=True,
        model_override="opus",
        options=_NO_EFFORT,
    )
    assert json.loads((artifacts / "agent_meta.json").read_text()) == {
        "llm_provider": "claude",
        "model": "opus",
        "exec_llm_provider": "fakey",
    }


def test_execution_override_resolves_display_model_with_requested_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_provider = MagicMock()
    execution_provider.invoke.return_value = InvokeResult(content="response")
    execution_provider.resolve_model_name.return_value = "fakey-large"
    requested_provider = MagicMock()
    requested_provider.resolve_model_name.return_value = "opus"
    monkeypatch.setenv("SASE_LLM_EXEC_PROVIDER", "fakey")

    with (
        patch(
            "sase.llm_provider._invoke.get_provider",
            side_effect=[execution_provider, requested_provider],
        ) as get_provider,
        patch("sase.llm_provider._invoke.postprocess_success") as postprocess,
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            provider_name="claude",
            suppress_output=True,
            skip_preprocessing=True,
        )

    assert [call.args for call in get_provider.call_args_list] == [
        ("fakey",),
        ("claude",),
    ]
    context = postprocess.call_args.kwargs["context"]
    assert context.metadata_llm_provider == "claude"
    assert context.metadata_model == "opus"


def test_invoke_agent_unknown_execution_provider_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_LLM_EXEC_PROVIDER", "missing-provider")

    with (
        patch(
            "sase.llm_provider._invoke.get_provider",
            side_effect=KeyError(
                "Unknown LLM provider: 'missing-provider'. Registered providers: "
                "['claude', 'fakey']"
            ),
        ) as get_provider,
        patch("sase.llm_provider._invoke.postprocess_error"),
        pytest.raises(
            LLMInvocationError,
            match="Unknown LLM provider: 'missing-provider'",
        ),
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            provider_name="claude",
            suppress_output=True,
            skip_preprocessing=True,
        )

    get_provider.assert_called_once_with("missing-provider")


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


def test_invoke_agent_consumes_pool_once_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider-less %model lane advances exactly once for each call."""
    from sase.llm_provider import config as llm_config

    config = {
        "provider": "claude",
        "model_aliases": {"builtin": {"pool": "claude/opus@medium | codex/gpt-5.5"}},
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
            "sase.llm_provider._invoke.run_commit_finalizer",
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
            "sase.llm_provider._invoke.resolve_model_provider_with_effort",
            return_value=(None, "unregistered-model", None),
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

    mock_resolve.assert_called_once_with("unregistered-model", consume=True)
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
        "model_aliases": {"builtin": {"default": "codex/gpt-5.6-sol"}},
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
        model_override="gpt-5.6-sol",
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
