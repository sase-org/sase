"""Tests for sase.gh_workspace module (GitHub-specific functions).

Generic utility tests (get_default_branch, parse_workspace_dir,
set_workspace_dir, ensure_git_clone) have moved to test_workspace_utils.py.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.gh_workspace import (
    detect_workflow_type_for_project,
    resolve_gh_ref,
)


class TestResolveGhRef:
    @patch("sase.gh_workspace.get_default_branch", return_value="origin/main")
    @patch("sase.gh_workspace.set_workspace_dir", return_value=True)
    @patch("sase.gh_workspace.parse_workspace_dir", return_value=None)
    @patch("sase.gh_workspace.os.path.isdir", return_value=True)
    def test_repo_path(
        self,
        mock_isdir: MagicMock,
        mock_parse: MagicMock,
        mock_set: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        result = resolve_gh_ref("alice/myrepo")
        assert result.project_name == "myrepo"
        assert result.checkout_target == "origin/main"
        assert "alice/myrepo" in result.primary_workspace_dir
        mock_set.assert_called_once()

    @patch("sase.gh_workspace.get_default_branch", return_value="origin/main")
    @patch("sase.gh_workspace.set_workspace_dir", return_value=True)
    @patch("sase.gh_workspace.parse_workspace_dir")
    def test_repo_path_conflict(
        self,
        mock_parse: MagicMock,
        mock_set: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        mock_parse.return_value = "/some/other/path/"
        with pytest.raises(ValueError, match="WORKSPACE_DIR conflict"):
            resolve_gh_ref("alice/myrepo")

    @patch("sase.gh_workspace.get_default_branch", return_value="origin/main")
    def test_project_shorthand(self, mock_branch: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch("sase.gh_workspace.Path.home", return_value=Path(d)):
                proj_dir = os.path.join(d, ".sase", "projects", "myproj")
                os.makedirs(proj_dir)
                gp = os.path.join(proj_dir, "myproj.gp")
                with open(gp, "w") as f:
                    f.write("WORKSPACE_DIR: /work/myproj/\nNAME: cl\n")

                result = resolve_gh_ref("myproj")
                assert result.project_name == "myproj"
                assert result.primary_workspace_dir == "/work/myproj/"
                assert result.checkout_target == "origin/main"

    @patch("sase.gh_workspace.get_default_branch", return_value="origin/main")
    @patch("sase.gh_workspace.find_all_changespecs")
    def test_changespec_name(
        self,
        mock_find: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "proj.gp")
            with open(gp, "w") as f:
                f.write("WORKSPACE_DIR: /work/proj/\nNAME: my-feature\n")

            cs = MagicMock()
            cs.name = "my-feature"
            cs.file_path = gp
            cs.project_basename = "proj"
            mock_find.return_value = [cs]

            # Need to fail mode 2 (project shorthand) first
            with patch(
                "sase.gh_workspace.Path.home",
                return_value=Path("/nonexistent"),
            ):
                result = resolve_gh_ref("my-feature")
                assert result.checkout_target == "origin/my-feature"
                assert result.project_name == "proj"

    @patch("sase.gh_workspace.find_all_changespecs")
    def test_changespec_no_workspace_dir(self, mock_find: MagicMock) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("NAME: my-feature\n")
            f.flush()

            cs = MagicMock()
            cs.name = "my-feature"
            cs.file_path = f.name
            cs.project_basename = "proj"
            mock_find.return_value = [cs]

            with patch(
                "sase.gh_workspace.Path.home",
                return_value=Path("/nonexistent"),
            ):
                with pytest.raises(ValueError, match="WORKSPACE_DIR is not set"):
                    resolve_gh_ref("my-feature")
            os.unlink(f.name)

    @patch("sase.gh_workspace.find_all_changespecs", return_value=[])
    def test_not_found(self, mock_find: MagicMock) -> None:
        with patch(
            "sase.gh_workspace.Path.home",
            return_value=Path("/nonexistent"),
        ):
            with pytest.raises(ValueError, match="Cannot resolve"):
                resolve_gh_ref("unknown-thing")

    def test_invalid_repo_path(self) -> None:
        with pytest.raises(ValueError, match="expected 'user/project'"):
            resolve_gh_ref("a/b/c")


# ── detect_workflow_type_for_project ─────────────────────────────────


class TestDetectWorkflowTypeForProject:
    def test_hg_no_git(self) -> None:
        """Returns 'hg' when no WORKSPACE_DIR or no .git directory."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("NAME: cl\n")
            f.flush()
            assert detect_workflow_type_for_project(f.name) == "hg"
            os.unlink(f.name)

    @patch("sase.gh_workspace.subprocess.run")
    def test_git_bare_repo_dir_set(self, mock_run: MagicMock) -> None:
        """Returns 'git' when BARE_REPO_DIR is set in project file."""
        with tempfile.TemporaryDirectory() as d:
            workspace = os.path.join(d, "repo")
            os.makedirs(os.path.join(workspace, ".git"))
            gp = os.path.join(d, "proj.gp")
            with open(gp, "w") as f:
                f.write(
                    f"WORKSPACE_DIR: {workspace}\n"
                    "BARE_REPO_DIR: /repos/proj.git\n"
                    "NAME: cl\n"
                )
            assert detect_workflow_type_for_project(gp) == "git"

    @patch("sase.gh_workspace.subprocess.run")
    def test_git_local_origin_url(self, mock_run: MagicMock) -> None:
        """Returns 'git' when origin remote URL is a local path."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="/home/user/repos/proj.git\n"
        )
        with tempfile.TemporaryDirectory() as d:
            workspace = os.path.join(d, "repo")
            os.makedirs(os.path.join(workspace, ".git"))
            gp = os.path.join(d, "proj.gp")
            with open(gp, "w") as f:
                f.write(f"WORKSPACE_DIR: {workspace}\nNAME: cl\n")
            assert detect_workflow_type_for_project(gp) == "git"

    @patch("sase.gh_workspace.subprocess.run")
    def test_gh_github_origin_url(self, mock_run: MagicMock) -> None:
        """Returns 'gh' when origin remote URL is a GitHub URL."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/user/repo.git\n"
        )
        with tempfile.TemporaryDirectory() as d:
            workspace = os.path.join(d, "repo")
            os.makedirs(os.path.join(workspace, ".git"))
            gp = os.path.join(d, "proj.gp")
            with open(gp, "w") as f:
                f.write(f"WORKSPACE_DIR: {workspace}\nNAME: cl\n")
            assert detect_workflow_type_for_project(gp) == "gh"
