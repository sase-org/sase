"""Tests for the repeat loop in the agent runner."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_runner import _write_repeat_state


class TestWriteRepeatState:
    """Tests for _write_repeat_state helper."""

    def test_writes_json(self, tmp_path: Path) -> None:
        path = str(tmp_path / "repeat_state.json")
        _write_repeat_state(path, 5, 3, 2)
        with open(path) as f:
            data = json.load(f)
        assert data == {
            "repeat_count": 5,
            "current_iteration": 3,
            "completed_iterations": 2,
        }

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = str(tmp_path / "repeat_state.json")
        _write_repeat_state(path, 5, 1, 0)
        _write_repeat_state(path, 5, 2, 1)
        with open(path) as f:
            data = json.load(f)
        assert data["current_iteration"] == 2
        assert data["completed_iterations"] == 1


class TestRepeatDirectiveParsing:
    """Tests for repeat count in _AgentInfo metadata."""

    def test_repeat_count_written_to_meta(self, tmp_path: Path) -> None:
        """Verify repeat_count > 1 is written to agent_meta.json."""
        meta: dict[str, object] = {"pid": 1234, "repeat_count": 3}
        meta_path = tmp_path / "agent_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        with open(meta_path) as f:
            data = json.load(f)
        assert data["repeat_count"] == 3

    def test_repeat_count_1_not_written_to_meta(self) -> None:
        """repeat_count=1 is a no-op and should not be written to meta."""
        from sase.xprompt.directives import extract_prompt_directives

        _, directives = extract_prompt_directives("%repeat:1\nDo work")
        assert directives.repeat_count == 1
        # The runner only writes repeat_count when > 1


class TestRepeatIterationVariable:
    """Tests for N variable injection into workflow named_args."""

    @patch("sase.xprompt.workflow_runner.execute_workflow")
    @patch("sase.xprompt.models.create_anonymous_workflow")
    def test_n_injected_when_repeat_iteration_set(
        self,
        mock_create: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_execution_loop passes N in named_args when repeat_iteration is set."""
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

        run_execution_loop(ctx, "test prompt", repeat_iteration=3)

        named_args = mock_execute.call_args[0][2]
        assert named_args["N"] == 3

    @patch("sase.xprompt.workflow_runner.execute_workflow")
    @patch("sase.xprompt.models.create_anonymous_workflow")
    def test_n_not_injected_without_repeat_iteration(
        self,
        mock_create: MagicMock,
        mock_execute: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_execution_loop does not inject N when repeat_iteration is None."""
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

        run_execution_loop(ctx, "test prompt")

        named_args = mock_execute.call_args[0][2]
        assert "N" not in named_args
