"""Tests for per-agent repeat context (n/N) read from SASE_REPEAT_* env vars."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestRepeatIterationEnv:
    """Tests for n/N variable injection via SASE_REPEAT_* env vars."""

    @patch("sase.xprompt.workflow_runner.execute_workflow")
    @patch("sase.xprompt.models.create_anonymous_workflow")
    def test_n_injected_when_repeat_env_set(
        self,
        mock_create: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_execution_loop reads n and N from SASE_REPEAT_* env vars."""
        from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop

        mock_wf = MagicMock()
        mock_wf.name = "anon"
        mock_wf.xprompts = {}
        mock_create.return_value = mock_wf
        mock_execute.return_value = MagicMock(response_text="done")

        ctx = MagicMock(spec=AgentExecContext)
        ctx.cl_name = "test"
        ctx.workspace_num = 1
        ctx.local_xprompts = {}
        ctx.artifacts_dir = str(tmp_path)
        ctx.is_home_mode = False
        ctx.project_name = "test"
        ctx.agent_name = None
        ctx.agent_model = None
        ctx.agent_llm_provider = None
        ctx.agent_vcs_provider = None
        ctx.agent_hidden = False
        ctx.timestamp = "2025-01-01"
        ctx.artifacts_timestamp = "20250101"
        ctx.project_file = "/tmp/test.gp"
        ctx.output_path = str(tmp_path / "output")

        monkeypatch.setenv("SASE_REPEAT_ITERATION", "3")
        monkeypatch.setenv("SASE_REPEAT_TOTAL", "5")

        run_execution_loop(ctx, "test prompt")

        named_args = mock_execute.call_args[0][2]
        assert named_args["n"] == 3
        assert named_args["N"] == 5

    @patch("sase.xprompt.workflow_runner.execute_workflow")
    @patch("sase.xprompt.models.create_anonymous_workflow")
    def test_n_absent_when_env_unset(
        self,
        mock_create: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_execution_loop does not set n/N when env vars are unset."""
        from sase.axe.run_agent_exec import AgentExecContext, run_execution_loop

        mock_wf = MagicMock()
        mock_wf.name = "anon"
        mock_wf.xprompts = {}
        mock_create.return_value = mock_wf
        mock_execute.return_value = MagicMock(response_text="done")

        ctx = MagicMock(spec=AgentExecContext)
        ctx.cl_name = "test"
        ctx.workspace_num = 1
        ctx.local_xprompts = {}
        ctx.artifacts_dir = str(tmp_path)
        ctx.is_home_mode = False
        ctx.project_name = "test"
        ctx.agent_name = None
        ctx.agent_model = None
        ctx.agent_llm_provider = None
        ctx.agent_vcs_provider = None
        ctx.agent_hidden = False
        ctx.timestamp = "2025-01-01"
        ctx.artifacts_timestamp = "20250101"
        ctx.project_file = "/tmp/test.gp"
        ctx.output_path = str(tmp_path / "output")

        monkeypatch.delenv("SASE_REPEAT_ITERATION", raising=False)
        monkeypatch.delenv("SASE_REPEAT_TOTAL", raising=False)

        run_execution_loop(ctx, "test prompt")

        named_args = mock_execute.call_args[0][2]
        assert "n" not in named_args
        assert "N" not in named_args
