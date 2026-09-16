"""Tests for run_agent_exec workflow project selection."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.gate_intent import GATE_INTENT_PREFIX, atomic_write_json
from sase.axe.run_agent_exec import (
    _AgentExecResult,
    _resolve_workflow_project,
    run_execution_loop,
)
from sase.llm_provider.gate_intent_guard import GateIntentLostError

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def test_resolve_workflow_project_non_home_mode_uses_workspace_provider(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(
        tmp_path,
        is_home_mode=False,
        project_name="gh_sase-org__sase",
    )

    with patch(
        "sase.workspace_provider.get_workspace_name",
        return_value="sase",
    ) as mock_get:
        assert _resolve_workflow_project(ctx) == "sase"

    mock_get.assert_called_once_with(ctx.workspace_dir)


def test_resolve_workflow_project_non_home_mode_returns_none_for_unknown_workspace(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(
        tmp_path,
        is_home_mode=False,
        project_name="gh_sase-org__sase",
    )

    with patch("sase.workspace_provider.get_workspace_name", return_value=None):
        assert _resolve_workflow_project(ctx) is None


def test_resolve_workflow_project_non_home_mode_returns_none_on_provider_error(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(
        tmp_path,
        is_home_mode=False,
        project_name="gh_sase-org__sase",
    )

    with patch("sase.workspace_provider.get_workspace_name", side_effect=RuntimeError):
        assert _resolve_workflow_project(ctx) is None


def test_resolve_workflow_project_home_mode_returns_none(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    assert _resolve_workflow_project(ctx) is None


def test_run_execution_loop_home_mode_passes_none_project(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(
        success=True,
        current_artifacts_dir=ctx.artifacts_dir,
    )

    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch(
            "sase.history.chat.get_chat_file_path",
            return_value="/tmp/test_chat.md",
        ),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch("sase.xprompt.workflow_runner.execute_workflow") as mock_execute,
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        result = run_execution_loop(ctx, "prompt")

    assert result == final_result
    assert mock_execute.call_count == 1
    assert mock_execute.call_args.kwargs["project"] is None


def test_run_execution_loop_non_home_mode_passes_workspace_provider_project(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(
        tmp_path,
        is_home_mode=False,
        project_name="gh_sase-org__sase",
    )
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(
        success=True,
        current_artifacts_dir=ctx.artifacts_dir,
    )

    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch(
            "sase.history.chat.get_chat_file_path",
            return_value="/tmp/test_chat.md",
        ),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch("sase.xprompt.workflow_runner.execute_workflow") as mock_execute,
        patch(
            "sase.workspace_provider.get_workspace_name",
            return_value="sase",
        ) as mock_get,
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        result = run_execution_loop(ctx, "prompt")

    assert result == final_result
    assert mock_execute.call_count == 1
    assert mock_execute.call_args.kwargs["project"] == "sase"
    mock_get.assert_called_once_with(ctx.workspace_dir)


def test_run_execution_loop_backstop_raises_lost_gate_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    anon_workflow = SimpleNamespace(name="anon", xprompts={})

    def _execute(*args: object, **kwargs: object) -> object:
        atomic_write_json(
            Path(ctx.artifacts_dir) / f"{GATE_INTENT_PREFIX}999999999.json",
            {
                "kind": "sudo",
                "request_id": "sudo-lost",
                "pid": 999999999,
                "process_identity": "",
                "timestamp": 1.0,
            },
        )
        return SimpleNamespace(continuation_prepared_ref=None)

    monkeypatch.setattr(
        "sase.llm_provider.gate_intent_guard._gate_shell_member_detail",
        lambda _intent: "",
    )
    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch("sase.history.chat.get_chat_file_path", return_value="/tmp/test_chat.md"),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch("sase.xprompt.workflow_runner.execute_workflow", side_effect=_execute),
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop") as finalize,
        pytest.raises(GateIntentLostError, match="sudo-lost"),
    ):
        run_execution_loop(ctx, "prompt")

    finalize.assert_not_called()


def test_run_execution_loop_converts_workflow_error_to_lost_gate_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    atomic_write_json(
        Path(ctx.artifacts_dir) / f"{GATE_INTENT_PREFIX}999999999.json",
        {
            "kind": "sudo",
            "request_id": "sudo-lost",
            "pid": 999999999,
            "process_identity": "",
            "timestamp": 1.0,
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.gate_intent_guard._gate_shell_member_detail",
        lambda _intent: "",
    )
    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch("sase.history.chat.get_chat_file_path", return_value="/tmp/test_chat.md"),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            side_effect=RuntimeError("429 Too Many Requests"),
        ),
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec.handle_workflow_error", return_value="raise"),
        pytest.raises(
            GateIntentLostError, match="provider error: 429 Too Many Requests"
        ),
    ):
        run_execution_loop(ctx, "prompt")
