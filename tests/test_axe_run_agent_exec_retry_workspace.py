"""Tests for run_agent_exec_retry workspace re-prep during retries."""

import dataclasses
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.core.occupancy_guard import WorkspaceOccupiedError
from sase.llm_provider.retry_config import ProviderRetryConfig
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record
from tests._axe_run_agent_exec_retry_helpers import (
    _restore_model_override_env,  # noqa: F401 (registers the autouse fixture)
    make_ctx_with_update_target,
    make_state,
)


def _preserve_cfg(max_retries: int = 2) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt="NUDGE",
        preserve_workspace=True,
    )


def _fallback_preserve_cfg() -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=0,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        fallback_model="backup-model",
        preserve_workspace=True,
    )


class TestHandleWorkflowErrorPreserveWorkspace:
    """preserve_workspace gates the in-loop prepare_workspace call."""

    def test_preserve_workspace_skips_prepare_on_retry(self, tmp_path: Path) -> None:
        ctx = make_ctx_with_update_target(tmp_path)
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=_preserve_cfg())

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("Prompt is too long"), tracker, ctx, state
            )

        assert action == "continue"
        mock_prepare.assert_not_called()

    def test_preserve_workspace_skips_prepare_on_fallback(self, tmp_path: Path) -> None:
        ctx = make_ctx_with_update_target(tmp_path)
        state = make_state("Do the work.")
        # max_retries=0 means we skip the retry branch and go to fallback.
        tracker = RetryTracker(retry_cfg=_fallback_preserve_cfg())

        try:
            with (
                patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
                patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
                patch(
                    "sase.axe.run_agent_exec_retry.prepare_workspace",
                    MagicMock(),
                ) as mock_prepare,
            ):
                action = handle_workflow_error(
                    RuntimeError("Prompt is too long"), tracker, ctx, state
                )

            assert action == "continue"
            assert tracker.using_fallback is True
            mock_prepare.assert_not_called()
        finally:
            os.environ.pop("SASE_MODEL_OVERRIDE", None)

    def test_default_preserve_workspace_false_still_calls_prepare(
        self, tmp_path: Path
    ) -> None:
        """Rate-limit retries (preserve_workspace=False default) still wipe — no regression."""
        ctx = make_ctx_with_update_target(tmp_path)
        state = make_state("Do the work.")
        cfg = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["rate limit"],
            wait_times=[0],
        )
        tracker = RetryTracker(retry_cfg=cfg)

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
        ):
            action = handle_workflow_error(
                RuntimeError("hit a rate limit"), tracker, ctx, state
            )

        assert action == "continue"
        mock_prepare.assert_called_once()


class TestHandleWorkflowErrorOccupancyGuard:
    """A retry re-prep must refuse rather than clobber a live occupant."""

    def test_refuses_when_workspace_is_occupied_by_another_live_agent(
        self, tmp_path: Path
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        other_pid = os.getppid()
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", delete=False, suffix=".sase"
        ) as f:
            f.write("# Test Project\n\nRUNNING:\n")
            f.write(
                WorkspaceClaim(
                    workspace_num=7,
                    workflow="ace(run)-other",
                    cl_name="test-cl",
                    pid=other_pid,
                    artifacts_timestamp="ts",
                ).to_line()
                + "\n"
            )
            f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
            project_file = f.name
        write_occupant_record(
            str(workspace_dir),
            new_occupant_record(
                pid=other_pid,
                workflow="ace(run)-other",
                project="sase",
                workspace_num=7,
                agent_name="rival-agent",
            ),
        )

        ctx = dataclasses.replace(
            make_ctx_with_update_target(tmp_path),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            project_file=project_file,
            workflow_name="ace(run)-mine",
        )
        state = make_state("Do the work.")
        tracker = RetryTracker(
            retry_cfg=ProviderRetryConfig(
                max_retries=2,
                error_patterns=["rate limit"],
                wait_times=[0],
            )
        )

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                MagicMock(),
            ) as mock_prepare,
            pytest.raises(WorkspaceOccupiedError, match="rival-agent"),
        ):
            handle_workflow_error(RuntimeError("hit a rate limit"), tracker, ctx, state)

        mock_prepare.assert_not_called()
