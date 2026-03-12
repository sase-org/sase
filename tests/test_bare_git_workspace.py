"""Tests for sase.workspace_provider.plugins.bare_git_* modules."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.plugins.bare_git_ref import (
    ResolvedGitRef,
    resolve_git_ref,
    set_bare_repo_dir,
)
from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

_REF_MOD = "sase.workspace_provider.plugins.bare_git_ref"
_INIT_MOD = "sase.workspace_provider.plugins.bare_git_init"


# ── set_bare_repo_dir ───────────────────────────────────────────────


class TestSetBareRepoDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "subdir", "proj.gp")
            assert set_bare_repo_dir(gp, "/repos/proj.git")
            assert os.path.exists(gp)

    @patch(f"{_REF_MOD}.write_changespec_atomic")
    @patch(f"{_REF_MOD}.changespec_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("BARE_REPO_DIR: /old/repo.git\nNAME: cl\n")
            f.flush()
            assert set_bare_repo_dir(f.name, "/new/repo.git")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "BARE_REPO_DIR: /new/repo.git" in written
            assert "/old/repo.git" not in written
            os.unlink(f.name)

    @patch(f"{_REF_MOD}.write_changespec_atomic")
    @patch(f"{_REF_MOD}.changespec_lock")
    def test_inserts_before_running(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("RUNNING:\n  #hg 1 1234\nNAME: cl\n")
            f.flush()
            assert set_bare_repo_dir(f.name, "/repos/proj.git")
            written = mock_write.call_args[0][1]
            lines = written.splitlines()
            bare_idx = next(
                i for i, ln in enumerate(lines) if ln.startswith("BARE_REPO_DIR:")
            )
            run_idx = next(i for i, ln in enumerate(lines) if ln.startswith("RUNNING:"))
            assert bare_idx < run_idx
            os.unlink(f.name)


# ── resolve_git_ref ──────────────────────────────────────────────────


class TestResolveGitRef:
    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    def test_project_shorthand(self, mock_branch: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                proj_dir = os.path.join(d, ".sase", "projects", "myproj")
                os.makedirs(proj_dir)
                gp = os.path.join(proj_dir, "myproj.gp")
                with open(gp, "w") as f:
                    f.write(
                        "WORKSPACE_DIR: /work/myproj/\n"
                        "BARE_REPO_DIR: /repos/myproj.git\n"
                        "NAME: cl\n"
                    )

                result = resolve_git_ref("myproj")
                assert isinstance(result, ResolvedGitRef)
                assert result.project_name == "myproj"
                assert result.primary_workspace_dir == "/work/myproj/"
                assert result.bare_repo_dir == "/repos/myproj.git"
                assert result.checkout_target == "origin/main"

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.find_all_changespecs")
    def test_changespec_name(
        self, mock_find: MagicMock, mock_branch: MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "proj.gp")
            with open(gp, "w") as f:
                f.write(
                    "WORKSPACE_DIR: /work/proj/\n"
                    "BARE_REPO_DIR: /repos/proj.git\n"
                    "NAME: my-feature\n"
                )

            cs = MagicMock()
            cs.name = "my-feature"
            cs.file_path = gp
            cs.project_basename = "proj"
            mock_find.return_value = [cs]

            with patch(
                f"{_REF_MOD}.Path.home",
                return_value=Path("/nonexistent"),
            ):
                result = resolve_git_ref("my-feature")
                assert result.checkout_target == "origin/my-feature"
                assert result.project_name == "proj"
                assert result.bare_repo_dir == "/repos/proj.git"

    @patch(f"{_REF_MOD}.find_all_changespecs", return_value=[])
    def test_not_found(self, mock_find: MagicMock) -> None:
        with patch(
            f"{_REF_MOD}.Path.home",
            return_value=Path("/nonexistent"),
        ):
            with pytest.raises(ValueError, match="Cannot resolve"):
                resolve_git_ref("unknown-thing")

    @patch(f"{_REF_MOD}.get_default_branch", return_value="origin/main")
    @patch(f"{_REF_MOD}.set_workspace_dir", return_value=True)
    @patch(f"{_REF_MOD}.set_bare_repo_dir", return_value=True)
    def test_bare_repo_path_strips_git_suffix(
        self,
        mock_set_bare: MagicMock,
        mock_set_ws: MagicMock,
        mock_branch: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                result = resolve_git_ref("/repos/foo.git")
                assert result.project_name == "foo"

    def test_invalid_empty_basename(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_REF_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(ValueError, match="Cannot derive project name"):
                    resolve_git_ref("/.git")


# ── init_bare_git_project ────────────────────────────────────────────


class TestInitBareGitProject:
    @patch(f"{_INIT_MOD}.set_workspace_dir", return_value=True)
    @patch(f"{_INIT_MOD}.set_bare_repo_dir", return_value=True)
    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_new_project(
        self,
        mock_run: MagicMock,
        mock_set_bare: MagicMock,
        mock_set_ws: MagicMock,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                bare_dir = os.path.join(d, "repos", "test.git")
                clone_dir = os.path.join(d, "projects", "test") + "/"
                result = init_bare_git_project(
                    "test", bare_dir=bare_dir, clone_dir=clone_dir
                )
                assert result.endswith("test.gp")
                # git init --bare, git clone, git config email,
                # git config name, git commit, git push
                assert mock_run.call_count == 6
                mock_set_bare.assert_called_once()
                mock_set_ws.assert_called_once()

    @patch(f"{_INIT_MOD}.set_workspace_dir", return_value=True)
    @patch(f"{_INIT_MOD}.set_bare_repo_dir", return_value=True)
    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_existing_bare(
        self,
        mock_run: MagicMock,
        mock_set_bare: MagicMock,
        mock_set_ws: MagicMock,
    ) -> None:
        # First call: git rev-parse --is-bare-repository → true
        # Second call: git clone
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="true\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                existing = os.path.join(d, "existing.git")
                os.makedirs(existing)
                clone_dir = os.path.join(d, "clone") + "/"
                result = init_bare_git_project(
                    "test", clone_dir=clone_dir, existing_bare=existing
                )
                assert result.endswith("test.gp")
                assert mock_run.call_count == 2
                # bare_dir should be the existing path
                mock_set_bare.assert_called_once_with(result, existing)

    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_invalid_existing_bare(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="false\n", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(RuntimeError, match="not a valid bare"):
                    init_bare_git_project(
                        "test",
                        clone_dir=os.path.join(d, "clone") + "/",
                        existing_bare="/some/dir",
                    )
