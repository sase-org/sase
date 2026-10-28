from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_runner_setup import (
    prepare_linked_repo_workspaces_if_needed,
    prepare_workspace_if_needed,
)
from sase.axe.runner_workspace import WorkspacePreparationError
from sase.linked_repos import LinkedRepoResolution, _ResolvedLinkedRepo
from sase.llm_provider.retry_config import ProviderRetryConfig
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.occupant import new_occupant_record, write_occupant_record
from sase.workspace_provider.utils import recreate_managed_workspace
from tests._axe_runner_workspace_reclone_helpers import claim_checkout_num7
from tests._axe_run_agent_exec_retry_helpers import (
    make_ctx_with_update_target,
    make_state,
)


def _project_file_with_claim(tmp_path: Path, claim: WorkspaceClaim) -> str:
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", delete=False, suffix=".sase"
    ) as f:
        f.write("# Test Project\n\nRUNNING:\n")
        f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\nDESCRIPTION:\n  Test\nSTATUS: Ready\n")
        return f.name


def _eligible_error(workspace_dir: str) -> WorkspacePreparationError:
    return WorkspacePreparationError(
        "self-heal postcondition failed: worktree is still dirty",
        step="verify",
        workspace_dir=workspace_dir,
        reclone_eligible=True,
    )


def _ineligible_fetch_error(workspace_dir: str) -> WorkspacePreparationError:
    return WorkspacePreparationError(
        "git fetch origin failed: exit 128: remote hung up unexpectedly",
        step="fetch",
        workspace_dir=workspace_dir,
        reclone_eligible=False,
    )


class TestRecreateRefusesPrimary:
    @pytest.mark.parametrize("workspace_num", [0, 1])
    def test_primary_checkout_is_never_recreated(
        self, tmp_path: Path, workspace_num: int
    ) -> None:
        primary = tmp_path / "primary"
        primary.mkdir()
        with pytest.raises(RuntimeError, match="numbered workspaces only"):
            recreate_managed_workspace(str(primary), workspace_num)
        assert list(tmp_path.iterdir()) == [primary]


class TestPrepareWorkspaceIfNeededReclone:
    def test_eligible_failure_recreates_and_prepares_again(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        project_file = claim_checkout_num7(tmp_path, workspace_dir)
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "sase.axe.run_agent_runner_setup_workspace.prepare_workspace",
                side_effect=[_eligible_error(str(workspace_dir)), None],
            ) as prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value=str(workspace_dir),
            ) as recreate,
            patch("sase.sdd.store.ensure_workspace_sdd_clone"),
            patch("sase.linked_repos.clear_workspace_repos"),
        ):
            prepare_workspace_if_needed(
                workspace_dir=str(workspace_dir),
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                project_file=project_file,
                workflow_name="ace(run)-mine",
                artifacts_timestamp="mine-ts",
                is_home_mode=False,
                retry_handoff=None,
            )

        assert prepare.call_count == 2
        recreate.assert_called_once_with(
            str(workspace_dir), 7, project_file=project_file
        )
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_dir)
        out = capsys.readouterr().out
        assert "could not be repaired in place" in out
        assert "re-creating it from the primary checkout" in out

    def test_ineligible_fetch_failure_skips_recreation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup_workspace.prepare_workspace",
                side_effect=[_ineligible_fetch_error("/tmp/workspace")],
            ),
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
            ) as recreate,
            pytest.raises(RuntimeError, match="remote hung up unexpectedly"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        recreate.assert_not_called()
        assert "could not be repaired in place" not in capsys.readouterr().out

    def test_primary_checkout_never_recreates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup_workspace.prepare_workspace",
                side_effect=[_eligible_error("/tmp/workspace")],
            ),
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
            ) as recreate,
            pytest.raises(RuntimeError, match="Failed to prepare workspace"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=1,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        recreate.assert_not_called()

    def test_second_failure_fails_the_launch(self, tmp_path: Path) -> None:
        with (
            patch(
                "sase.axe.run_agent_runner_setup_workspace.prepare_workspace",
                side_effect=[
                    _eligible_error("/tmp/workspace"),
                    _eligible_error("/tmp/workspace"),
                ],
            ) as prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value="/tmp/workspace",
            ) as recreate,
            patch(
                "sase.axe.run_agent_runner_setup_workspace.enter_agent_workspace",
            ),
            pytest.raises(RuntimeError, match="Failed to prepare workspace"),
        ):
            prepare_workspace_if_needed(
                workspace_dir="/tmp/workspace",
                workspace_num=7,
                cl_name="feature",
                update_target="main",
                project_name="sase",
                is_home_mode=False,
                retry_handoff=None,
            )

        assert prepare.call_count == 2
        recreate.assert_called_once()


class TestRetryPrepareWorkspaceReclone:
    def _retry_cfg(self) -> ProviderRetryConfig:
        return ProviderRetryConfig(
            max_retries=2,
            error_patterns=["rate limit"],
            wait_times=[0],
        )

    def test_retry_reprep_recreates_on_eligible_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        project_file = claim_checkout_num7(tmp_path, workspace_dir)
        monkeypatch.chdir(tmp_path)
        ctx = dataclasses.replace(
            make_ctx_with_update_target(tmp_path),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            project_file=project_file,
            workflow_name="ace(run)-mine",
        )
        state = make_state("Do the work.")
        tracker = RetryTracker(retry_cfg=self._retry_cfg())

        with (
            patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
            patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
            patch(
                "sase.axe.run_agent_exec_retry.prepare_workspace",
                side_effect=[_eligible_error(str(workspace_dir)), None],
            ) as mock_prepare,
            patch(
                "sase.workspace_provider.utils.recreate_managed_workspace",
                return_value=str(workspace_dir),
            ) as recreate,
        ):
            action = handle_workflow_error(
                RuntimeError("hit a rate limit"), tracker, ctx, state
            )

        assert action == "continue"
        assert mock_prepare.call_count == 2
        recreate.assert_called_once_with(
            str(workspace_dir), 7, project_file=project_file
        )
        assert os.path.realpath(os.getcwd()) == os.path.realpath(workspace_dir)


class TestLinkedRepoPrepareReclone:
    def test_linked_clone_recreates_on_eligible_failure(self, tmp_path: Path) -> None:
        primary_dir = tmp_path / "primary"
        primary_dir.mkdir()
        linked_dir = tmp_path / "linked"
        linked_dir.mkdir()
        project_file = _project_file_with_claim(
            tmp_path,
            WorkspaceClaim(
                workspace_num=7,
                workflow="ace(run)-mine",
                cl_name="feature",
                pid=os.getpid(),
                artifacts_timestamp="mine-ts",
            ),
        )
        write_occupant_record(
            str(primary_dir),
            new_occupant_record(
                pid=os.getpid(),
                workflow="ace(run)-mine",
                project="sase",
                workspace_num=7,
            ),
        )
        resolution = LinkedRepoResolution(
            repos=(
                _ResolvedLinkedRepo(
                    name="docs",
                    env_name="DOCS",
                    primary_dir=str(tmp_path / "docs-primary"),
                    workspace_dir=str(linked_dir),
                    workspace_num=7,
                    auto_clone=True,
                ),
            )
        )

        env_before = set(os.environ)
        try:
            with (
                patch(
                    "sase.linked_repos.materialize_linked_repo_workspace",
                    return_value=str(linked_dir),
                ) as materialize,
                patch(
                    "sase.axe.run_agent_runner_setup_linked_repos.prepare_workspace",
                    side_effect=[_eligible_error(str(linked_dir)), None],
                ) as prepare,
            ):
                prepare_linked_repo_workspaces_if_needed(
                    resolution=resolution,
                    cl_name="feature",
                    primary_workspace_dir=str(primary_dir),
                    workspace_num=7,
                    project_name="sase",
                    project_file=project_file,
                    workflow_name="ace(run)-mine",
                    artifacts_timestamp="mine-ts",
                )
        finally:
            for key in set(os.environ) - env_before:
                del os.environ[key]

        assert materialize.call_count == 2
        assert prepare.call_count == 2
