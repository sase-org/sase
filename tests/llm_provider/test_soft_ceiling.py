"""Soft-ceiling export (`SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS`)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sase.env_contracts import (
    SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV,
    SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV,
)
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult, LLMInvocationError


def _run_invoke_with_soft_ceiling(
    soft: int | None,
    monkeypatch: pytest.MonkeyPatch,
    *,
    previous_soft: str | None = None,
    fail: bool = False,
) -> dict[str, str | None]:
    """Run invoke_agent with a stub provider; capture the env seen by invoke."""
    seen: dict[str, str | None] = {}

    def _invoke(prompt: str, **kwargs: object) -> InvokeResult:
        seen["during_soft"] = os.environ.get(
            SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV
        )
        seen["during_hard"] = os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
        if fail:
            raise RuntimeError("boom")
        return InvokeResult(content="ok")

    provider = MagicMock()
    provider.sync_ceiling_seconds.return_value = 600
    provider.invoke.side_effect = _invoke
    provider.resolve_model_name.side_effect = RuntimeError("no model")
    monkeypatch.delenv(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, raising=False)
    if previous_soft is None:
        monkeypatch.delenv(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV, raising=False)
    else:
        monkeypatch.setenv(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV, previous_soft)
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch("sase.llm_provider._invoke.postprocess_error"),
        patch(
            "sase.config.tools.get_tool_runs_soft_ceiling_seconds",
            return_value=soft,
        ),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        if fail:
            with pytest.raises(LLMInvocationError):
                invoke_agent("prompt", agent_type="test", suppress_output=True)
        else:
            invoke_agent("prompt", agent_type="test", suppress_output=True)
    seen["after_soft"] = os.environ.get(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV)
    return seen


def test_invoke_agent_sets_and_restores_the_soft_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _run_invoke_with_soft_ceiling(1200, monkeypatch)
    assert seen["during_soft"] == "1200"
    assert seen["during_hard"] == "600"
    assert seen["after_soft"] is None


def test_invoke_agent_restores_a_previous_soft_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _run_invoke_with_soft_ceiling(1200, monkeypatch, previous_soft="prev")
    assert seen["during_soft"] == "1200"
    assert seen["after_soft"] == "prev"


def test_invoke_agent_pops_an_inherited_soft_ceiling_when_none_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _run_invoke_with_soft_ceiling(None, monkeypatch, previous_soft="600")
    assert seen["during_soft"] is None
    assert seen["after_soft"] == "600"


def test_invoke_agent_restores_the_soft_ceiling_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _run_invoke_with_soft_ceiling(300, monkeypatch, fail=True)
    assert seen["during_soft"] == "300"
    assert seen["after_soft"] is None


def test_invoke_agent_pops_the_soft_ceiling_when_the_getter_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str | None] = {}

    def _invoke(prompt: str, **kwargs: object) -> InvokeResult:
        seen["during_soft"] = os.environ.get(
            SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV
        )
        return InvokeResult(content="ok")

    provider = MagicMock()
    provider.sync_ceiling_seconds.return_value = 600
    provider.invoke.side_effect = _invoke
    provider.resolve_model_name.side_effect = RuntimeError("no model")
    monkeypatch.delenv(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV, raising=False)
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.config.tools.get_tool_runs_soft_ceiling_seconds",
            side_effect=RuntimeError("config broken"),
        ),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        invoke_agent("prompt", agent_type="test", suppress_output=True)
    assert seen["during_soft"] is None
