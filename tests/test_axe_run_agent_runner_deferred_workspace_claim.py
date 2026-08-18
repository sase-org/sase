"""Tests for deferred workspace allocation in the agent runner."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import (
    ClaimResult,
    WorkspaceClaim,
    WorkspaceClaimError,
    get_claimed_workspaces,
)


def _write_project_file(
    tmp_path: Path, running_claims: list[WorkspaceClaim] | None = None
) -> str:
    project_file = tmp_path / "project.sase"
    lines = ["# Test Project\n"]
    if running_claims:
        lines.append("RUNNING:\n")
        for claim in running_claims:
            lines.append(claim.to_line() + "\n")
    lines.extend(["NAME: Test Feature\n", "STATUS: Ready\n"])
    project_file.write_text("".join(lines))
    return str(project_file)


class TestDeferredWorkspacePreparation:
    def test_claim_deferred_workspace_claims_and_returns_real_workspace(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        release_mock = MagicMock()
        claim_next = MagicMock(return_value=7)

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.claim_next_axe_workspace", claim_next),
            patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            ws_dir.return_value = (str(workspace_dir), None)

            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 7
        assert actual_workspace_dir == str(workspace_dir)
        release_mock.assert_called_once_with(
            str(tmp_path / "project.sase"),
            0,
            "test-workflow",
            "test-cl",
            caller_tag="deferred-placeholder-release",
        )
        claim_next.assert_called_once()
        chdir_mock.assert_called_once_with(str(workspace_dir))

    def test_claim_deferred_workspace_writes_occupant_record(
        self, tmp_path: Path
    ) -> None:
        """A successful deferred claim must name itself as the occupant."""
        from sase.axe.run_agent_phases import claim_deferred_workspace
        from sase.workspace_provider.occupant import read_occupant_record

        workspace_dir = tmp_path / "ws7"

        with (
            patch("sase.running_field.release_workspace"),
            patch("sase.running_field.claim_next_axe_workspace", return_value=7),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
        ):
            claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        occupant = read_occupant_record(str(workspace_dir))
        assert occupant is not None
        assert occupant.pid == os.getpid()
        assert occupant.workspace_num == 7
        assert occupant.workflow == "test-workflow"
        assert occupant.project == "test-project"
        assert occupant.cl_name == "test-cl"

    def test_claim_deferred_workspace_sets_active_project_dir_on_chdir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runner chdir must also rewrite SASE_ACTIVE_PROJECT_DIR."""
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        resolved_sdd = workspace_dir / ".custom-sdd"
        monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", "/stale/parent")
        monkeypatch.setenv("SASE_SDD_DIR", "/stale/sdd")
        monkeypatch.setattr(
            "sase.sdd.store.resolve_sdd_dir",
            lambda workspace, workspace_num: resolved_sdd,
        )

        with (
            patch("sase.running_field.release_workspace"),
            patch("sase.running_field.claim_next_axe_workspace", return_value=7),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
        ):
            claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert os.environ["SASE_ACTIVE_PROJECT_DIR"] == str(workspace_dir)
        assert os.environ["SASE_SDD_DIR"] == str(resolved_sdd)

    def test_claim_deferred_workspace_recomputes_linked_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace
        from sase.linked_repos import (
            LINKED_REPOS_JSON_ENV,
            SIBLING_REPOS_JSON_ENV,
            resolve_linked_repos_for_project,
        )

        workspace_dir = tmp_path / "ws7"
        primary = tmp_path / "sase"
        sibling = tmp_path / "sase-core"
        primary.mkdir()
        sibling.mkdir()
        project_file = tmp_path / "project.sase"
        project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: main\n")
        linked_workspace = (
            primary.with_name("sase_7") / "sase" / "repos" / "linked" / "core"
        )
        linked_workspace.mkdir(parents=True)
        resolution = resolve_linked_repos_for_project(
            project_file=str(project_file),
            workspace_dir=str(workspace_dir),
            workspace_num=7,
            config={
                "workspace": {"root": "adjacent"},
                "linked_repos": [{"name": "core", "path": "../sase-core"}],
            },
            materialize=False,
        )
        monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "stale")

        with (
            patch("sase.running_field.release_workspace"),
            patch("sase.running_field.claim_next_axe_workspace", return_value=7),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
            patch(
                "sase.linked_repos.resolve_linked_repos_for_project",
                return_value=resolution,
            ),
        ):
            claim_deferred_workspace(
                str(project_file),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        # Canonical linked env plus the deprecated sibling alias are recomputed.
        assert os.environ["SASE_LINKED_REPO_CORE_DIR"] == str(linked_workspace)
        assert os.environ["SASE_SIBLING_REPO_CORE_DIR"] == str(linked_workspace)
        assert json.loads(os.environ[LINKED_REPOS_JSON_ENV])[0]["name"] == "core"
        assert json.loads(os.environ[SIBLING_REPOS_JSON_ENV])[0]["name"] == "core"

    def test_claim_deferred_workspace_retries_claim_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "2")
        release_mock = MagicMock()
        claim_next = MagicMock(
            side_effect=[WorkspaceClaimError("claim race"), 8],
        )

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.claim_next_axe_workspace", claim_next),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(tmp_path / "ws8"), None),
            ),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 8
        assert actual_workspace_dir == str(tmp_path / "ws8")
        assert claim_next.call_count == 2
        chdir_mock.assert_called_once_with(str(tmp_path / "ws8"))

    def test_claim_deferred_workspace_exhaustion_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "1")

        with (
            patch("sase.running_field.release_workspace"),
            patch(
                "sase.running_field.claim_next_axe_workspace",
                side_effect=WorkspaceClaimError("claim rejected"),
            ),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            with pytest.raises(SystemExit) as exc_info:
                claim_deferred_workspace(
                    str(tmp_path / "project.sase"),
                    "test-project",
                    "test-workflow",
                    "test-cl",
                    "20260316_120000",
                )

        assert exc_info.value.code == 1
        assert "Failed to claim a real workspace after dependencies completed" in (
            capsys.readouterr().err
        )
        chdir_mock.assert_not_called()

    def test_claim_deferred_workspace_skips_number_claimed_at_claim_time(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        occupied = WorkspaceClaim(10, "ace(run)-other", "other-agent", pid=11111)
        project_file = _write_project_file(tmp_path, running_claims=[occupied])
        resolved = {11: str(tmp_path / "ws11")}

        with (
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=lambda num, _project: (resolved[num], None),
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
        ):
            workspace_num, workspace_dir = claim_deferred_workspace(
                project_file,
                "test-project",
                "test-workflow",
                "test-cl",
                "260316_120000",
            )

        assert workspace_num != 10
        assert workspace_num == 11
        assert workspace_dir == resolved[11]
        claimed_nums = {
            claim.workspace_num for claim in get_claimed_workspaces(project_file)
        }
        assert 10 in claimed_nums
        assert workspace_num in claimed_nums

    def test_claim_deferred_workspace_releases_on_materialize_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "2")
        release_mock = MagicMock()
        claim_next = MagicMock(side_effect=[7, 8])

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.claim_next_axe_workspace", claim_next),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[
                    RuntimeError("clone failed"),
                    (str(tmp_path / "ws8"), None),
                ],
            ),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.sase"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 8
        assert actual_workspace_dir == str(tmp_path / "ws8")
        released_nums = [call.args[1] for call in release_mock.call_args_list]
        assert released_nums[0] == 0
        assert 7 in released_nums
        chdir_mock.assert_called_once_with(str(tmp_path / "ws8"))

    def test_pinned_target_held_by_live_pid_fails_with_occupant(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        occupant_pid = os.getpid()
        occupied = WorkspaceClaim(
            17,
            "ace(run)-260818_125956",
            "06e--plan",
            pid=occupant_pid,
            artifacts_timestamp="260818_125956",
        )
        project_file = _write_project_file(tmp_path, running_claims=[occupied])
        monkeypatch.setenv("SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM", "17")
        claim_next = MagicMock()

        with (
            patch("sase.running_field.claim_next_axe_workspace", claim_next),
            patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            with pytest.raises(SystemExit) as exc_info:
                claim_deferred_workspace(
                    project_file,
                    "test-project",
                    "test-workflow",
                    "family-child",
                    "20260818_130000",
                )

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Pinned workspace #17 is already claimed by" in err
        assert "06e--plan" in err
        assert f"pid {occupant_pid}" in err
        assert "live" in err
        claim_next.assert_not_called()
        ws_dir.assert_not_called()
        chdir_mock.assert_not_called()
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == occupant_pid
        assert claims[0].workspace_num == 17

    def test_pinned_target_claim_is_single_shot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        monkeypatch.setenv("SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM", "17")
        monkeypatch.setenv("SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES", "4")
        claim_workspace_mock = MagicMock(
            return_value=ClaimResult(
                success=False, error="workspace #17 is already claimed"
            )
        )

        with (
            patch("sase.running_field.release_workspace"),
            patch("sase.running_field.claim_workspace", claim_workspace_mock),
            patch(
                "sase.running_field.get_claimed_workspaces",
                return_value=[
                    WorkspaceClaim(17, "ace(run)-other", "other-agent", pid=os.getpid())
                ],
            ),
            patch("sase.axe.run_agent_phases.os.chdir"),
        ):
            with pytest.raises(SystemExit):
                claim_deferred_workspace(
                    str(tmp_path / "project.sase"),
                    "test-project",
                    "test-workflow",
                    "family-child",
                    "20260818_130000",
                )

        assert claim_workspace_mock.call_count == 1
