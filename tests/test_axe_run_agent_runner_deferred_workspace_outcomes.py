"""Tests for deferred workspace runner stops and failures."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.axe.run_agent_repeat_stop import RepeatStopDecision
from sase.linked_repos import LinkedRepoResolution

from tests._axe_run_agent_runner_retry_helpers import (
    AGENT_INFO,
    BOOTSTRAP,
    LAUNCH,
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
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )
        patches[f"{RUNNER}.wait_for_dependencies"] = MagicMock()
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
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
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop
        claim_mock = MagicMock(
            side_effect=AssertionError("stopped slot must not claim a workspace")
        )
        patches[f"{LAUNCH}.claim_deferred_workspace"] = claim_mock
        claim_bead_mock = MagicMock(
            side_effect=AssertionError("stopped slot must not claim a bead")
        )
        patches[f"{LAUNCH}.claim_bead_for_agent_launch"] = claim_bead_mock

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

    def test_deferred_workspace_without_extracted_wait_still_claims_real_workspace(
        self, tmp_path: Path
    ) -> None:
        """A conservative deferred launch without wait metadata still runs.

        Regression for the composition bug from plan
        ``202608/repair_failed_agent_fork_launch.md``: launch preflight
        can conservatively mark a launch as deferred even when later
        preprocessing or compatibility normalization leaves no extracted wait
        metadata at all. That combination - ``deferred_workspace=True`` with
        ``has_wait=False`` - must not be treated as a bootstrap failure: it
        must skip dependency wait machinery entirely and still claim a real,
        nonzero workspace before the run loop ever executes.
        """
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        meta_path = Path(artifacts_dir) / "agent_meta.json"
        events: list[str] = []

        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(
                wait_names=[],
                wait_duration=None,
                wait_until=None,
                wait_runners=None,
                wait_priority=None,
            )
        )
        wait_for_dependencies = MagicMock()
        write_error = MagicMock()

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 3, str(real_ws)

        def run_loop(ctx: Any, _prompt: str) -> Any:
            events.append("run")
            # Execution must observe the claimed real workspace, never the
            # placeholder path/number the run was launched with.
            assert ctx.workspace_num == 3
            assert ctx.workspace_num != 0
            assert ctx.workspace_dir == str(real_ws)
            assert ctx.workspace_dir != str(placeholder_ws)
            meta = json.loads(meta_path.read_text())
            assert meta["workspace_num"] == 3
            assert meta["workspace_dir"] == str(real_ws)
            return exec_result(artifacts_dir)

        patches[f"{RUNNER}.wait_for_dependencies"] = wait_for_dependencies
        patches[f"{LAUNCH}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{LAUNCH}.claim_deferred_workspace"] = MagicMock(
            side_effect=claim_deferred
        )
        patches[f"{LAUNCH}.refresh_linked_repos_for_workspace"] = MagicMock(
            return_value=LinkedRepoResolution(repos=())
        )
        patches[f"{LAUNCH}.run_execution_loop"] = MagicMock(side_effect=run_loop)
        patches[f"{RUNNER}.write_error_done_marker"] = write_error

        run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == ["claim", "run"]
        wait_for_dependencies.assert_not_called()
        write_error.assert_not_called()

    def test_bead_claim_failure_writes_error_and_skips_model_execution(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        run_loop = MagicMock(return_value=exec_result(artifacts_dir))
        write_error = MagicMock()
        claim_bead = MagicMock(side_effect=RuntimeError("claim failed"))

        patches = base_patches(artifacts_dir)
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            return_value=AGENT_INFO._replace(bead_id="sase-8f.2")
        )
        patches[f"{LAUNCH}.claim_bead_for_agent_launch"] = claim_bead
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop
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
        patches[f"{BOOTSTRAP}.extract_directives_and_write_meta"] = MagicMock(
            side_effect=RuntimeError(
                "%id bead association 'sase-8f.2' does not match "
                "SASE_BEAD_ID='sase-other'"
            )
        )
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop
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
        patches[f"{LAUNCH}.claim_bead_for_agent_launch"] = claim_bead
        patches[f"{LAUNCH}.run_execution_loop"] = run_loop

        run_main(patches, tmp_path)

        claim_bead.assert_not_called()
        run_loop.assert_called_once()
