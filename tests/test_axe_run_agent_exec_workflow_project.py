"""Tests for run_agent_exec workflow project selection."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import (
    _AgentExecResult,
    _resolve_workflow_project,
    run_execution_loop,
)

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
