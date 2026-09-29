"""Provider synchronous-ceiling export (`SASE_PROVIDER_SYNC_CEILING_SECONDS`)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sase.env_contracts import SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV
from sase.feature_flags import override_flags
from sase.llm_provider._invoke import _provider_sync_ceiling_seconds, invoke_agent
from sase.llm_provider._plugin_manager import validate_sync_ceiling_seconds
from sase.llm_provider.claude import ClaudeCodeProvider, _claude_sync_ceiling_seconds
from sase.llm_provider.muse import MuseProvider
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.registry import create_provider
from sase.llm_provider.types import InvokeResult


def test_muse_ceiling_is_600_with_sync_shell_on() -> None:
    with override_flags(muse_synchronous_shell=True):
        assert MuseProvider().sync_ceiling_seconds() == 600
        assert MuseProvider().llm_sync_ceiling_seconds() == 600


def test_muse_ceiling_is_none_with_sync_shell_off() -> None:
    with override_flags(muse_synchronous_shell=False):
        assert MuseProvider().sync_ceiling_seconds() is None
        assert MuseProvider().llm_sync_ceiling_seconds() is None


def test_claude_ceiling_defaults_to_four_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BASH_MAX_TIMEOUT_MS", raising=False)
    assert _claude_sync_ceiling_seconds() == 14400
    assert ClaudeCodeProvider().sync_ceiling_seconds() == 14400


def test_claude_ceiling_honors_a_valid_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BASH_MAX_TIMEOUT_MS", "3600000")
    assert _claude_sync_ceiling_seconds() == 3600


@pytest.mark.parametrize("raw", ["not-a-number", "", "0", "-5"])
def test_claude_ceiling_falls_back_on_garbage(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("BASH_MAX_TIMEOUT_MS", raw)
    assert _claude_sync_ceiling_seconds() == 14400


def test_provider_without_the_hook_declares_no_ceiling() -> None:
    assert create_provider("fakey").sync_ceiling_seconds() is None


@pytest.mark.parametrize("value", [True, False, "600", 600.0, 0, -5, None])
def test_validation_rejects_non_positive_integers(value: object) -> None:
    assert validate_sync_ceiling_seconds(value) is None


def test_validation_accepts_a_positive_int() -> None:
    assert validate_sync_ceiling_seconds(600) == 600


def test_invoke_helper_treats_an_exception_as_no_ceiling() -> None:
    provider = MagicMock()
    provider.sync_ceiling_seconds.side_effect = RuntimeError("boom")
    assert _provider_sync_ceiling_seconds(provider) is None


def test_invoke_helper_treats_a_missing_accessor_as_no_ceiling() -> None:
    assert _provider_sync_ceiling_seconds(object()) is None


def _run_invoke_with_ceiling(
    ceiling: int | None, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str | None]:
    """Run invoke_agent with a stub provider; capture the env seen by invoke."""
    seen: dict[str, str | None] = {}

    def _invoke(prompt: str, **kwargs: object) -> InvokeResult:
        seen["during"] = os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
        return InvokeResult(content="ok")

    provider = MagicMock()
    provider.sync_ceiling_seconds.return_value = ceiling
    provider.invoke.side_effect = _invoke
    provider.resolve_model_name.side_effect = RuntimeError("no model")
    monkeypatch.delenv(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, raising=False)
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        invoke_agent("prompt", agent_type="test", suppress_output=True)
    seen["after"] = os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
    return seen


def test_invoke_agent_sets_and_restores_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _run_invoke_with_ceiling(600, monkeypatch)
    assert seen["during"] == "600"
    assert seen["after"] is None


def test_invoke_agent_pops_an_inherited_ceiling_when_none_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, "600")
    seen: dict[str, str | None] = {}

    def _invoke(prompt: str, **kwargs: object) -> InvokeResult:
        seen["during"] = os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV)
        return InvokeResult(content="ok")

    provider = MagicMock()
    provider.sync_ceiling_seconds.return_value = None
    provider.invoke.side_effect = _invoke
    provider.resolve_model_name.side_effect = RuntimeError("no model")
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=lambda **kw: kw["invoke_result"],
        ),
    ):
        invoke_agent("prompt", agent_type="test", suppress_output=True)
    assert seen["during"] is None
    assert os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV) == "600"


def test_invoke_agent_restores_the_ceiling_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.types import LLMInvocationError

    provider = MagicMock()
    provider.sync_ceiling_seconds.return_value = 600
    provider.invoke.side_effect = RuntimeError("boom")
    monkeypatch.delenv(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, raising=False)
    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.postprocess_error"),
        pytest.raises(LLMInvocationError),
    ):
        invoke_agent("prompt", agent_type="test", suppress_output=True)
    assert os.environ.get(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV) is None
