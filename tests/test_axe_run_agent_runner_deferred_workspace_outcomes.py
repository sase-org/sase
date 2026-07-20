"""Tests for deferred workspace runner stops and failures."""

from pathlib import Path
from unittest.mock import MagicMock

from sase.axe.run_agent_repeat_stop import RepeatStopDecision

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    RUNNER,
    base_patches,
    exec_result,
    run_main,
)


class TestDeferredWorkspaceOutcomes:
    def test_repeat_stop_exits_before_workspace_claim_and_run_loop(
        self, tmp_path: Path
    ) -> None:
        """A repeat STOP after the wait skips the deferred claim and execution.

        Output variables must be written before the done marker, and the run
        must finish successfully with its completion notification suppressed.
        """
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        placeholder_ws.mkdir()
        order: list[str] = []

        wait_info = AGENT_INFO._replace(wait_names=["foo.1"], bead_id="sase-8f.2")
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        patches[f"{RUNNER}.wait_for_dependencies"] = MagicMock()
        patches[f"{RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{RUNNER}.detect_repeat_stop"] = MagicMock(
            return_value=RepeatStopDecision(producer_name="foo.1", stop_value="1")
        )
        gate_mock = patches[f"{RUNNER}.wait_for_runner_slot"]

        set_vars_mock = MagicMock(side_effect=lambda *a, **k: order.append("set_vars"))
        write_done_mock = MagicMock(
            side_effect=lambda *a, **k: order.append("write_done")
        )
        patches[f"{RUNNER}.set_agent_output_variables"] = set_vars_mock
        patches[f"{RUNNER}.write_done_marker_and_update_index"] = write_done_mock

        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        claim_mock = MagicMock(
            side_effect=AssertionError("stopped slot must not claim a workspace")
        )
        patches[f"{RUNNER}.claim_deferred_workspace"] = claim_mock
        claim_bead_mock = MagicMock(
            side_effect=AssertionError("stopped slot must not claim a bead")
        )
        patches[f"{RUNNER}.claim_bead_for_agent_launch"] = claim_bead_mock

        notify_mock = MagicMock()
        patches[f"{RUNNER}.send_completion_notification"] = notify_mock
        patches[f"{RUNNER}.all_steps_hidden"] = MagicMock(return_value=False)

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        run_loop.assert_not_called()
        gate_mock.assert_not_called()
        claim_mock.assert_not_called()
        claim_bead_mock.assert_not_called()
        # Output variables are propagated before the completed done marker.
        assert order == ["set_vars", "write_done"]
        set_vars_mock.assert_called_once_with(artifacts_dir, {"STOP": "1"})
        # The done marker is a completed, repeat-stopped slot.
        done_marker = write_done_mock.call_args.args[1]
        assert done_marker["outcome"] == "completed"
        assert done_marker["repeat_stopped"] is True
        assert done_marker["stopped_by"] == "foo.1"
        # Completion notification is suppressed for a stopped slot.
        notify_mock.assert_not_called()

    def test_deferred_workspace_without_extracted_wait_fails_before_run_loop(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        placeholder_ws.mkdir()
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        write_error = MagicMock()

        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(
                wait_names=[],
                wait_duration=None,
                wait_until=None,
                wait_runners=None,
            )
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        run_loop.assert_not_called()
        assert (
            "SASE_AGENT_DEFERRED_WORKSPACE=1" in write_error.call_args.kwargs["error"]
        )

    def test_bead_claim_failure_writes_error_and_skips_model_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        write_error = MagicMock()
        claim_bead = MagicMock(side_effect=RuntimeError("claim failed"))

        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(bead_id="sase-8f.2")
        )
        patches[f"{RUNNER}.claim_bead_for_agent_launch"] = claim_bead
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(patches, tmp_path)

        claim_bead.assert_called_once()
        run_loop.assert_not_called()
        assert "claim failed" in write_error.call_args.kwargs["error"]

    def test_bead_environment_mismatch_writes_error_and_skips_model_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        write_error = MagicMock()
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            side_effect=RuntimeError(
                "%id bead association 'sase-8f.2' does not match "
                "SASE_BEAD_ID='sase-other'"
            )
        )
        patches[f"{RUNNER}.run_execution_loop"] = run_loop
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(patches, tmp_path)

        run_loop.assert_not_called()
        assert "does not match SASE_BEAD_ID" in write_error.call_args.kwargs["error"]

    def test_launch_without_bead_never_invokes_claim_helper(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        claim_bead = MagicMock(
            side_effect=AssertionError("legacy launches must not claim a bead")
        )
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        patches = base_patches(artifacts_dir)
        patches[f"{RUNNER}.claim_bead_for_agent_launch"] = claim_bead
        patches[f"{RUNNER}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        claim_bead.assert_not_called()
        run_loop.assert_called_once()
