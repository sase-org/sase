"""Tests for deferred workspace allocation in the agent runner."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.running_field import ClaimResult


class TestDeferredWorkspacePreparation:
    def test_claim_deferred_workspace_claims_and_returns_real_workspace(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        release_mock = MagicMock()
        claim_mock = MagicMock(return_value=ClaimResult(success=True))

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
            patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
            patch("sase.running_field.claim_workspace", claim_mock),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            first_ws.return_value = 7
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
            str(tmp_path / "project.sase"), 0, "test-workflow", "test-cl"
        )
        claim_mock.assert_called_once()
        chdir_mock.assert_called_once_with(str(workspace_dir))

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
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                return_value=7,
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=True),
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
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                return_value=7,
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                return_value=(str(workspace_dir), None),
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=True),
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
        claim_mock = MagicMock(
            side_effect=[
                ClaimResult(success=False, error="claim race"),
                ClaimResult(success=True),
            ]
        )

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch(
                "sase.running_field.get_first_available_axe_workspace",
                side_effect=[7, 8],
            ) as first_ws,
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[
                    (str(tmp_path / "ws7"), None),
                    (str(tmp_path / "ws8"), None),
                ],
            ),
            patch("sase.running_field.claim_workspace", claim_mock),
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
        assert first_ws.call_count == 2
        assert claim_mock.call_count == 2
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
                "sase.running_field.get_first_available_axe_workspace",
                side_effect=[7, 8],
            ),
            patch(
                "sase.running_field.get_workspace_directory_for_num",
                side_effect=[
                    (str(tmp_path / "ws7"), None),
                    (str(tmp_path / "ws8"), None),
                ],
            ),
            patch(
                "sase.running_field.claim_workspace",
                return_value=ClaimResult(success=False, error="claim rejected"),
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
