"""Tests for sase.workspace_provider.utils module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.utils import (
    ensure_git_clone,
    get_default_branch,
    parse_bare_repo_dir,
    parse_workspace_dir,
    set_workspace_dir,
)


# ── get_default_branch ─────────────────────────────────────────────


class TestGetDefaultBranch:
    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_detects_main(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n"
        )
        assert get_default_branch("/repo") == "origin/main"

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fallback_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_default_branch("/repo") == "origin/main"

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fallback_on_exception(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("no git")
        assert get_default_branch("/repo") == "origin/main"


# ── parse_workspace_dir ──────────────────────────────────────────────


class TestParseWorkspaceDir:
    def test_empty_value(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("WORKSPACE_DIR:\nNAME: my-cl\n")
            f.flush()
            assert parse_workspace_dir(f.name) is None
            os.unlink(f.name)


# ── parse_bare_repo_dir ──────────────────────────────────────────────


class TestParseBareRepoDir:
    def test_missing_file(self) -> None:
        assert parse_bare_repo_dir("/nonexistent/path/file.gp") is None

    def test_empty_value(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("BARE_REPO_DIR:\nNAME: my-cl\n")
            f.flush()
            assert parse_bare_repo_dir(f.name) is None
            os.unlink(f.name)


# ── set_workspace_dir ────────────────────────────────────────────────


class TestSetWorkspaceDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "subdir", "proj.gp")
            assert set_workspace_dir(gp, "/repo/")
            assert os.path.exists(gp)

    @patch("sase.workspace_provider.utils.write_changespec_atomic")
    @patch("sase.workspace_provider.utils.changespec_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("WORKSPACE_DIR: /old/\nNAME: cl\n")
            f.flush()
            assert set_workspace_dir(f.name, "/new/")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "WORKSPACE_DIR: /new/" in written
            assert "/old/" not in written
            os.unlink(f.name)

    @patch("sase.workspace_provider.utils.write_changespec_atomic")
    @patch("sase.workspace_provider.utils.changespec_lock")
    def test_inserts_before_running(
        self, mock_lock: MagicMock, mock_write: MagicMock
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
            f.write("RUNNING:\n  #hg 1 1234\nNAME: cl\n")
            f.flush()
            assert set_workspace_dir(f.name, "/repo/")
            written = mock_write.call_args[0][1]
            lines = written.splitlines()
            ws_idx = next(
                i for i, ln in enumerate(lines) if ln.startswith("WORKSPACE_DIR:")
            )
            run_idx = next(i for i, ln in enumerate(lines) if ln.startswith("RUNNING:"))
            assert ws_idx < run_idx
            os.unlink(f.name)


class TestEnsureGitClone:
    def test_primary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = ensure_git_clone(d, 1)
            assert result == d

    def test_primary_missing(self) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            ensure_git_clone("/nonexistent/dir/", 1)

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_secondary_creates(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "repo") + "/"
            os.makedirs(primary)
            result = ensure_git_clone(primary, 2)
            expected = os.path.join(d, "repo") + "_2/"
            assert result == expected
            # Should have called: get-url, clone, set-url, fetch
            assert mock_run.call_count == 4

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_secondary_fails(self, mock_run: MagicMock) -> None:
        import subprocess as sp

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="https://github.com/u/r.git\n"),  # get-url
            sp.CalledProcessError(1, "git", stderr="fatal error"),  # clone fails
        ]
        with tempfile.TemporaryDirectory() as d:
            primary = os.path.join(d, "repo") + "/"
            os.makedirs(primary)
            with pytest.raises(RuntimeError, match="git clone failed"):
                ensure_git_clone(primary, 2)
