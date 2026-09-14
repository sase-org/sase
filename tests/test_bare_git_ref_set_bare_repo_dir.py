"""Tests for sase.workspace_provider.plugins.bare_git_ref.set_bare_repo_dir."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.workspace_provider.plugins.bare_git_ref import set_bare_repo_dir

_REF_MOD = "sase.workspace_provider.plugins.bare_git_ref"


class TestSetBareRepoDir:
    def test_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            gp = os.path.join(d, "subdir", "proj.sase")
            assert set_bare_repo_dir(gp, "/repos/proj.git")
            assert os.path.exists(gp)

    @patch(f"{_REF_MOD}.write_patch_atomic")
    @patch(f"{_REF_MOD}.patch_lock")
    def test_updates_existing(
        self, mock_lock: MagicMock, mock_write: MagicMock, tmp_path: Path
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("BARE_REPO_DIR: /old/repo.git\nNAME: cl\n")
            f.flush()
            assert set_bare_repo_dir(f.name, "/new/repo.git")
            mock_write.assert_called_once()
            written = mock_write.call_args[0][1]
            assert "BARE_REPO_DIR: /new/repo.git" in written
            assert "/old/repo.git" not in written
            os.unlink(f.name)

    @patch(f"{_REF_MOD}.write_patch_atomic")
    @patch(f"{_REF_MOD}.patch_lock")
    def test_inserts_before_running(
        self, mock_lock: MagicMock, mock_write: MagicMock, tmp_path: Path
    ) -> None:
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock(return_value=False)
        with tempfile.NamedTemporaryFile(
            dir=tmp_path, mode="w", suffix=".sase", delete=False
        ) as f:
            f.write("RUNNING:\n  #git 1 1234\nNAME: cl\n")
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
