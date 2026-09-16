"""Tests for llm_provider invoke_agent orchestration.

Covers success and error paths, usage-limit detection at the invoke call
site, preprocess shadow measurements, and monitor continuation-budget
refusal. Env and compatibility overrides live in
``test_llm_provider_invoke_overrides.py``; model-alias, pool, and
default-model routing live in ``test_llm_provider_invoke_routing.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.gate_intent import GATE_INTENT_PREFIX, atomic_write_json
from sase.agent._family_attach_types import FAMILY_ATTACH_ENV
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.continuation_budget import (
    CONTINUATION_BUDGET_DECISION_FILENAME,
    CONTINUATION_BUDGET_ENFORCE_ENV,
    MONITOR_CONTINUATION_ENV,
)
from sase.llm_provider.types import LLMInvocationOptions
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult, LLMInvocationError
from tests._llm_provider_invoke_helpers import (
    _clear_execution_provider_override,  # noqa: F401 (registers the autouse fixture)
)


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


@patch("sase.llm_provider._invoke.handle_possible_usage_limit")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_does_not_detect_usage_limit_on_generic_exception(
    mock_postprocess_error: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_handle_usage_limit: MagicMock,
) -> None:
    """An arbitrary internal error is not provider-attributable evidence of a
    usage limit, so detection must not run on the generic Exception path."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.side_effect = Exception("test error")
    mock_get_provider.return_value = mock_provider

    with pytest.raises(LLMInvocationError):
        invoke_agent("raw prompt", agent_type="test", suppress_output=True)

    mock_handle_usage_limit.assert_not_called()


@patch("sase.llm_provider._invoke.handle_possible_usage_limit")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_detects_usage_limit_on_called_process_error(
    mock_postprocess_error: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_handle_usage_limit: MagicMock,
) -> None:
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.side_effect = subprocess.CalledProcessError(
        1, ["cmd"], output="", stderr="You've hit your usage limit."
    )
    mock_get_provider.return_value = mock_provider

    with pytest.raises(LLMInvocationError):
        invoke_agent(
            "raw prompt",
            agent_type="test",
            provider_name="claude",
            suppress_output=True,
        )

    mock_handle_usage_limit.assert_called_once()
    kwargs = mock_handle_usage_limit.call_args.kwargs
    assert kwargs["provider"] == "claude"
    assert "You've hit your usage limit." in kwargs["error_text"]


@patch("sase.llm_provider._invoke.handle_possible_usage_limit")
@patch("sase.llm_provider._invoke.get_provider")
@patch("sase.llm_provider._invoke.preprocess_prompt")
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_detects_usage_limit_on_llm_invocation_error(
    mock_postprocess_error: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    mock_handle_usage_limit: MagicMock,
) -> None:
    """Providers that fail through a parsed stream (not a nonzero exit) reach
    this path, so detection must run here too."""
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed prompt")
    mock_provider = MagicMock()
    mock_provider.invoke.side_effect = LLMInvocationError("usage limit reached")
    mock_get_provider.return_value = mock_provider

    with pytest.raises(LLMInvocationError):
        invoke_agent(
            "raw prompt",
            agent_type="test",
            provider_name="codex",
            suppress_output=True,
        )

    mock_handle_usage_limit.assert_called_once()
    kwargs = mock_handle_usage_limit.call_args.kwargs
    assert kwargs["provider"] == "codex"
    assert kwargs["error_text"] == "usage limit reached"


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
@patch("sase.llm_provider._invoke.postprocess_error")
def test_invoke_agent_lost_gate_intent_fails_before_finalizers(
    mock_postprocess_error: MagicMock,
    mock_postprocess_success: MagicMock,
    mock_preprocess: MagicMock,
    mock_get_provider: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    atomic_write_json(
        artifacts / f"{GATE_INTENT_PREFIX}999999999.json",
        {
            "kind": "sudo",
            "request_id": "sudo-lost",
            "source": "sase sudo request",
            "pid": 999999999,
            "process_identity": "",
            "timestamp": 1.0,
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.gate_intent_guard._gate_shell_member_detail",
        lambda _intent: "",
    )
    mock_preprocess.return_value = _PreprocessResult(prompt="preprocessed")
    mock_provider = MagicMock()
    mock_provider.invoke.return_value = InvokeResult(content="provider response")
    mock_get_provider.return_value = mock_provider

    with (
        patch("sase.finalizers.run_finalizers") as run_finalizers,
        pytest.raises(LLMInvocationError, match="gate intent lost:"),
    ):
        invoke_agent(
            "prompt",
            agent_type="test",
            suppress_output=True,
            artifacts_dir=str(artifacts),
        )

    run_finalizers.assert_not_called()
    mock_postprocess_success.assert_not_called()
    mock_postprocess_error.assert_called_once()


def test_invoke_agent_records_provider_preprocess_shadow_measurement(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="response")

    def passthrough_finalizers(**kwargs: object) -> InvokeResult:
        result = kwargs["invoke_result"]
        assert isinstance(result, InvokeResult)
        return result

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch("sase.finalizers.run_finalizers", side_effect=passthrough_finalizers),
    ):
        invoke_agent(
            "hello provider",
            agent_type="test",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
        )

    [record] = [
        json.loads(line)
        for line in (artifacts / "continuation_prompt_measurements.jsonl")
        .read_text()
        .splitlines()
    ]
    assert record["component"] == "provider_preprocess"
    submitted_prompt = provider.invoke.call_args.args[0]
    assert record["prompt_sizes"]["total_expanded_bytes"] == len(
        submitted_prompt.encode()
    )
    assert record["fallback_routing"] == {
        "active": False,
        "model": "large",
        "provider": "fakey",
    }


def test_monitor_continuation_budget_refusal_records_nonlaunchable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    parent = tmp_path / "monitor-parent"
    parent.mkdir()
    (parent / "agent_meta.json").write_text(
        json.dumps(
            {
                "monitor_id": "m1",
                "monitor_followup_outcome": "launched",
            }
        ),
        encoding="utf-8",
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="should not run")
    monkeypatch.setenv(MONITOR_CONTINUATION_ENV, "1")
    monkeypatch.setenv("SASE_CONTINUATION_CONTEXT_LIMIT_BYTES", "32")
    monkeypatch.setenv(
        FAMILY_ATTACH_ENV,
        json.dumps({"parent_artifacts_dir": str(parent)}),
    )

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_error") as postprocess_error,
        patch("sase.llm_provider._invoke.handle_possible_usage_limit"),
        pytest.raises(
            LLMInvocationError,
            match="Continuation context budget exceeded",
        ),
    ):
        invoke_agent(
            "x" * 100,
            agent_type="agent",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_not_called()
    postprocess_error.assert_called_once()

    decision_path = artifacts / CONTINUATION_BUDGET_DECISION_FILENAME
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["decision"]["kind"] == "refuse"
    assert decision["decision"]["disposition"] == "context_budget_exceeded"

    child_meta = json.loads((artifacts / "agent_meta.json").read_text())
    assert child_meta["continuation_budget_kind"] == "refuse"
    assert child_meta["continuation_budget_disposition"] == "context_budget_exceeded"
    assert child_meta["continuation_budget_target_bytes"] == 32

    parent_meta = json.loads((parent / "agent_meta.json").read_text())
    assert parent_meta["monitor_followup_outcome"] == "not-launchable"
    assert (
        "Continuation context budget exceeded" in parent_meta["monitor_followup_error"]
    )
    assert parent_meta["monitor_followup_budget_decision_path"] == str(decision_path)
    assert parent_meta["monitor_followup_prompt_path"] == str(
        artifacts / "agent_prompt.md"
    )


def test_monitor_continuation_budget_compacts_raw_output_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.continuation_budget_spans import open_reducible_span_marker

    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="ok")
    provider.resolve_model_name.return_value = "fake-model"
    open_marker, close_marker = open_reducible_span_marker(kind="old_raw_excerpts")
    prompt = "\n".join(
        [
            "# Monitored command finished",
            "",
            "Protected objective stays visible.",
            "",
            "## Last 100 lines of output",
            "",
            open_marker,
            "```text",
            "RAW_SENTINEL " + ("x" * 900),
            "```",
            close_marker,
            "",
            "## Your next action",
            "",
            "Keep NEXT_SENTINEL and continue from the retained result.",
        ]
    )
    monkeypatch.setenv(CONTINUATION_BUDGET_ENFORCE_ENV, "1")
    monkeypatch.setenv("SASE_CONTINUATION_CONTEXT_LIMIT_BYTES", "420")

    def passthrough_finalizers(**kwargs: object) -> InvokeResult:
        result = kwargs["invoke_result"]
        assert isinstance(result, InvokeResult)
        return result

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch("sase.finalizers.run_finalizers", side_effect=passthrough_finalizers),
    ):
        invoke_agent(
            prompt,
            agent_type="agent",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    submitted_prompt = provider.invoke.call_args.args[0]
    assert "RAW_SENTINEL" not in submitted_prompt
    assert "Raw output excerpt omitted by continuation budget" in submitted_prompt
    assert "NEXT_SENTINEL" in submitted_prompt

    decision_path = artifacts / CONTINUATION_BUDGET_DECISION_FILENAME
    record = json.loads(decision_path.read_text(encoding="utf-8"))
    assert record["decision"]["kind"] == "compact"
    assert [item["kind"] for item in record["decision"]["reductions"]] == [
        "old_raw_excerpts"
    ]
    assert (
        record["request"]["essential_bytes"]
        < record["request"]["rendered_prompt_bytes"]
    )
    projected_path = Path(record["projected_prompt_path"])
    assert projected_path.read_text(encoding="utf-8") == submitted_prompt

    child_meta = json.loads((artifacts / "agent_meta.json").read_text())
    assert child_meta["continuation_budget_kind"] == "compact"
    assert child_meta["continuation_budget_projected_prompt_path"] == str(
        projected_path
    )


def test_monitor_continuation_budget_never_drops_authored_selected_diagnostics_heading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the audit's authored-heading failure.

    An authored ``## Selected diagnostics`` heading is not, by itself,
    evidence of a genuinely reducible section -- only a render-emitted
    marker pair from ``continuation_budget_spans`` is. Without a real
    marker, oversized content following that heading must refuse rather
    than silently disappear the way heading-regex discovery used to.
    """
    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="should not run")
    provider.resolve_model_name.return_value = "fake-model"
    protected_instruction = "PROTECTED_SENTINEL " + ("y" * 900)
    prompt = "\n".join(
        [
            "# Monitored command finished",
            "",
            "## Selected diagnostics",
            "",
            protected_instruction,
            "",
            "## Your next action",
            "",
            "Keep going.",
        ]
    )
    monkeypatch.setenv(CONTINUATION_BUDGET_ENFORCE_ENV, "1")
    monkeypatch.setenv("SASE_CONTINUATION_CONTEXT_LIMIT_BYTES", "420")

    with (
        patch("sase.llm_provider._invoke.get_provider", return_value=provider),
        patch("sase.llm_provider._invoke.postprocess_error"),
        patch("sase.llm_provider._invoke.handle_possible_usage_limit"),
        pytest.raises(
            LLMInvocationError,
            match="Continuation context budget exceeded",
        ),
    ):
        invoke_agent(
            prompt,
            agent_type="agent",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_not_called()

    decision_path = artifacts / CONTINUATION_BUDGET_DECISION_FILENAME
    record = json.loads(decision_path.read_text(encoding="utf-8"))
    assert record["decision"]["kind"] == "refuse"
    assert record["decision"]["reductions"] == []
    assert (
        record["request"]["essential_bytes"]
        == record["request"]["rendered_prompt_bytes"]
    )


def test_continuation_budget_uses_provider_transport_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import continuation_budget_request as budget_request_module

    monkeypatch.setattr(
        "sase.llm_provider.config.get_llm_provider_config",
        lambda: {"continuation_budget": {}},
    )

    request = budget_request_module.budget_request(
        "small prompt",
        {},
        provider_name="agy",
        model_tier="large",
        model_name="gemini-3.7-flash-high",
        options=LLMInvocationOptions(),
    )

    assert request["provider_budget"]["transport_limit_bytes"] == 120 * 1024
    assert request["provider_budget"]["instruction_reserve_bytes"] >= 512
