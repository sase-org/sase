"""Mocked unit tests for sase.workspace_provider.plugins.bare_git_init."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.plugins.bare_git_init import init_bare_git_project

_INIT_MOD = "sase.workspace_provider.plugins.bare_git_init"


class TestInitBareGitProject:
    def test_git_runner_removes_persistent_index_lock_after_retries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.git_lock_retry import ENV_GIT_LOCK_RETRY_DELAYS
        from sase.workspace_provider.plugins.bare_git_init import _run_git

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        tracked = tmp_path / "tracked.txt"
        tracked.write_text("content\n", encoding="utf-8")
        lock_path = tmp_path / ".git" / "index.lock"
        lock_path.touch()
        monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.001")

        result = _run_git(["add", "tracked.txt"], cwd=tmp_path)

        assert result.returncode == 0
        assert not lock_path.exists()

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
                assert result.endswith("test.sase")
                # git init --bare, git clone, git config email,
                # git config name, git add generated SDD files, git commit, git push
                assert mock_run.call_count == 7
                commit_calls = [
                    call.args[0]
                    for call in mock_run.call_args_list
                    if "commit" in call.args[0] and "-m" in call.args[0]
                ]
                assert commit_calls
                message = commit_calls[0][commit_calls[0].index("-m") + 1]
                assert message == "Initial commit\n\nSASE_TYPE=init"
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
        # Second call: git show-ref --quiet → has refs
        # Third call: git clone
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="true\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)),
                patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
            ):
                existing = os.path.join(d, "existing.git")
                os.makedirs(existing)
                clone_dir = os.path.join(d, "clone") + "/"
                result = init_bare_git_project(
                    "test", clone_dir=clone_dir, existing_bare=existing
                )
                assert result.endswith("test.sase")
                assert mock_run.call_count == 3
                # bare_dir should be the existing path
                mock_set_bare.assert_called_once_with(result, existing)
                ensure_sdd.assert_called_once_with(
                    clone_dir,
                    commit=True,
                    push=True,
                    raise_on_error=True,
                )

    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_invalid_existing_bare(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="false\n", stderr="")
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                existing = os.path.join(d, "some", "dir")
                os.makedirs(existing)
                with pytest.raises(RuntimeError, match="not a valid bare"):
                    init_bare_git_project(
                        "test",
                        clone_dir=os.path.join(d, "clone") + "/",
                        existing_bare=existing,
                    )

    @patch(f"{_INIT_MOD}.subprocess.run")
    def test_hidden_project_name_is_rejected_before_git_commands(
        self, mock_run: MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch(f"{_INIT_MOD}.Path.home", return_value=Path(d)):
                with pytest.raises(ValueError, match="invalid SASE project name"):
                    init_bare_git_project(
                        ".sase",
                        bare_dir=os.path.join(d, ".sase.git"),
                        clone_dir=os.path.join(d, ".sase") + "/",
                    )

        mock_run.assert_not_called()
