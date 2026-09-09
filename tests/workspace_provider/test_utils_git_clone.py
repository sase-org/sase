"""Tests for ensure_git_clone_at primary validation, fresh clone, and replacement."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workspace_provider.utils import ensure_git_clone_at


# ── ensure_git_clone_at (Phase 2 target-aware materializer) ──────────


class TestEnsureGitCloneAt:
    def test_primary_validated_at_explicit_target(self, tmp_path: Path) -> None:
        primary = tmp_path / "repo"
        primary.mkdir()
        # workspace_num=0 (new PRIMARY identity) returns the supplied target
        result = ensure_git_clone_at(str(primary), 0, str(primary))
        assert result == str(primary)

    def test_legacy_primary_num_one(self, tmp_path: Path) -> None:
        primary = tmp_path / "repo"
        primary.mkdir()
        result = ensure_git_clone_at(str(primary), 1, str(primary))
        assert result == str(primary)

    def test_primary_missing_raises(self) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            ensure_git_clone_at("/nonexistent/dir", 0, "/nonexistent/dir")

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_creates_clone_at_explicit_target(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/u/r.git\n"
        )
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "managed" / "repo_10"  # parent doesn't exist
        result = ensure_git_clone_at(str(primary) + "/", 10, str(target) + "/")
        assert result == str(target) + "/"
        # Parent should have been created
        assert target.parent.is_dir()
        # 4 subprocess calls: get-url, clone, set-url, fetch
        assert mock_run.call_count == 4
        clone_kwargs = mock_run.call_args_list[1].kwargs
        fetch_kwargs = mock_run.call_args_list[3].kwargs
        assert clone_kwargs["stdin"] is subprocess.DEVNULL
        assert clone_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert fetch_kwargs["stdin"] is subprocess.DEVNULL
        assert fetch_kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fresh_clone_raises_when_primary_origin_command_errors(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        def run(cmd: list[str], **_kwargs: object) -> MagicMock:
            if cmd == ["git", "remote", "get-url", "origin"]:
                return MagicMock(returncode=1, stdout="", stderr="config locked")
            raise AssertionError(f"unexpected command: {cmd}")

        mock_run.side_effect = run
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"

        with pytest.raises(RuntimeError, match="could not read origin URL"):
            ensure_git_clone_at(str(primary), 2, str(target))

        assert not target.exists()

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_corrupt_target_is_replaced(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        # First call: git status on existing target — non-zero (corrupt)
        # Then: get-url, clone, set-url, fetch
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # git status fails
            MagicMock(returncode=0, stdout="https://github.com/u/r.git\n"),  # get-url
            MagicMock(returncode=0, stdout=""),  # clone
            MagicMock(returncode=0, stdout=""),  # set-url
            MagicMock(returncode=0, stdout=""),  # fetch
        ]
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"
        target.mkdir()
        # Drop a junk file so we can confirm shutil.rmtree ran
        (target / "stale.txt").write_text("garbage")

        result = ensure_git_clone_at(str(primary) + "/", 2, str(target) + "/")
        assert result == str(target) + "/"
        assert not (target / "stale.txt").exists()
        assert mock_run.call_count == 5

    @patch("sase.workspace_provider.utils.subprocess.run")
    def test_fresh_clone_raises_when_primary_origin_returns_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="fatal: could not read config\n",
        )
        primary = tmp_path / "repo"
        primary.mkdir()
        target = tmp_path / "repo_2"

        with pytest.raises(RuntimeError, match="Could not read primary.*origin"):
            ensure_git_clone_at(str(primary), 2, str(target))

        commands = [call.args[0] for call in mock_run.call_args_list]
        assert commands == [["git", "remote", "get-url", "origin"]]
        assert not target.exists()
