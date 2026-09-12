"""Tests for invoke_agent env and compatibility overrides.

Covers ``SASE_LLM_EXEC_PROVIDER``, deprecated ``model_size``, and the
``SASE_MODEL_TIER_OVERRIDE`` / ``SASE_MODEL_SIZE_OVERRIDE`` env vars.
Call-site success/error orchestration lives in
``test_llm_provider_invoke.py``; model-alias routing lives in
``test_llm_provider_invoke_routing.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult, LLMInvocationError
from sase.xprompt.directives import PromptDirectives
from tests._llm_provider_invoke_helpers import (
    _NO_EFFORT,
    _assert_get_provider_called_once,
    _clear_execution_provider_override,  # noqa: F401 (registers the autouse fixture)
)


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
        provider_name="claude",
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

    _assert_get_provider_called_once(get_provider, "fakey")
    submitted_prompt = provider.invoke.call_args.args[0]
    assert submitted_prompt == "prompt"
    assert (artifacts / "test_prompt.md").read_text(encoding="utf-8") == "prompt"
    assert provider.invoke.call_args.kwargs == {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": "opus",
        "options": _NO_EFFORT,
    }
    meta = json.loads((artifacts / "agent_meta.json").read_text())
    assert meta["llm_provider"] == "claude"
    assert meta["model"] == "opus"
    assert meta["exec_llm_provider"] == "fakey"
    assert meta["finalizers"]["selected"] == ["commit"]


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

    _assert_get_provider_called_once(get_provider, "missing-provider")


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
            provider_name="claude",
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
            provider_name="claude",
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
