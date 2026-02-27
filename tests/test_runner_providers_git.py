"""Tests for the built-in GitRunnerProvider."""

import os
import subprocess
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from sase.runner_provider import RunnerContext, get_runner_providers
from sase.runner_providers.git import (
    GitRunnerProvider,
    _capture_git_diff,
    _prepare_git_workspace,
    allocate_workspace,
)


@dataclass
class _FakeResolved:
    project_name: str = "myproject"
    project_file: str = "/home/user/.sase/projects/myproject/myproject.gp"
    primary_workspace_dir: str = "/home/user/projects/myproject"
    bare_repo_dir: str = "/home/user/.sase/bare/myproject.git"
    checkout_target: str = "main"


# ---------------------------------------------------------------------------
# allocate_workspace tests
# ---------------------------------------------------------------------------


_GIT_MOD = "sase.runner_providers.git"


class TestAllocateWorkspace:
    """Tests for the allocate_workspace() helper."""

    @patch(f"{_GIT_MOD}.claim_workspace")
    @patch(f"{_GIT_MOD}.get_first_available_axe_workspace", return_value=101)
    @patch(
        f"{_GIT_MOD}.ensure_git_clone",
        return_value="/home/user/projects/myproject__101",
    )
    @patch(f"{_GIT_MOD}.resolve_git_ref", return_value=_FakeResolved())
    def test_auto_allocate(
        self,
        mock_resolve: MagicMock,
        mock_clone: MagicMock,
        mock_avail: MagicMock,
        mock_claim: MagicMock,
    ) -> None:
        ctx = allocate_workspace("myproject")

        mock_resolve.assert_called_once_with("myproject")
        mock_avail.assert_called_once_with(
            "/home/user/.sase/projects/myproject/myproject.gp"
        )
        mock_clone.assert_called_once_with("/home/user/projects/myproject", 101)
        mock_claim.assert_called_once()

        assert ctx.project_name == "myproject"
        assert ctx.workspace_num == 101
        assert ctx.workspace_dir == "/home/user/projects/myproject__101"
        assert ctx.should_release is True

    @patch(f"{_GIT_MOD}.claim_workspace")
    @patch(
        f"{_GIT_MOD}.ensure_git_clone", return_value="/home/user/projects/myproject__5"
    )
    @patch(f"{_GIT_MOD}.resolve_git_ref", return_value=_FakeResolved())
    def test_explicit_n(
        self,
        mock_resolve: MagicMock,
        mock_clone: MagicMock,
        mock_claim: MagicMock,
    ) -> None:
        ctx = allocate_workspace("myproject", n=5)

        mock_clone.assert_called_once_with("/home/user/projects/myproject", 5)
        assert ctx.workspace_num == 5

    @patch(f"{_GIT_MOD}.claim_workspace")
    @patch(f"{_GIT_MOD}.resolve_git_ref", return_value=_FakeResolved())
    def test_pre_allocated_env(
        self,
        mock_resolve: MagicMock,
        mock_claim: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SASE_GIT_PRE_ALLOCATED", "1")
        monkeypatch.setenv("SASE_GIT_WORKSPACE_NUM", "42")
        monkeypatch.setenv("SASE_GIT_WORKSPACE_DIR", "/tmp/ws42")

        ctx = allocate_workspace("myproject")

        assert ctx.workspace_num == 42
        assert ctx.workspace_dir == "/tmp/ws42"


# ---------------------------------------------------------------------------
# _prepare_git_workspace tests
# ---------------------------------------------------------------------------


def _make_completed(
    stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestPrepareGitWorkspace:
    """Tests for _prepare_git_workspace()."""

    @patch(f"{_GIT_MOD}._run_git")
    def test_clean_workspace(self, mock_git: MagicMock) -> None:
        # diff --quiet succeeds (clean)
        # checkout . succeeds
        # clean -fd succeeds
        # fetch succeeds
        # pull succeeds
        # rev-parse HEAD returns hash
        mock_git.side_effect = [
            _make_completed(returncode=0),  # diff --quiet
            _make_completed(),  # checkout .
            _make_completed(),  # clean -fd
            _make_completed(),  # fetch
            _make_completed(),  # pull
            _make_completed(stdout="abc123\n"),  # rev-parse HEAD
        ]

        head = _prepare_git_workspace("/tmp/ws")
        assert head == "abc123"
        assert mock_git.call_count == 6

    @patch(f"{_GIT_MOD}._run_git")
    def test_dirty_workspace_saves_backup(
        self, mock_git: MagicMock, tmp_path: object
    ) -> None:
        # diff --quiet fails (dirty)
        mock_git.side_effect = [
            _make_completed(returncode=1),  # diff --quiet → dirty
            _make_completed(stdout="diff content\n"),  # diff HEAD (backup)
            _make_completed(),  # checkout .
            _make_completed(),  # clean -fd
            _make_completed(),  # fetch
            _make_completed(),  # pull
            _make_completed(stdout="def456\n"),  # rev-parse HEAD
        ]

        head = _prepare_git_workspace("/tmp/ws")
        assert head == "def456"
        # 7 calls: dirty check, backup diff, checkout, clean, fetch, pull, rev-parse
        assert mock_git.call_count == 7


# ---------------------------------------------------------------------------
# _capture_git_diff tests
# ---------------------------------------------------------------------------


class TestCaptureGitDiff:
    """Tests for _capture_git_diff()."""

    @patch(f"{_GIT_MOD}._run_git")
    def test_committed_changes(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = [
            _make_completed(stdout="new-head\n"),  # rev-parse HEAD
            _make_completed(stdout="--- a/file\n+++ b/file\n"),  # diff HEAD~1 HEAD
        ]

        result = _capture_git_diff("/tmp/ws", "old-head")
        assert result is not None
        with open(result) as f:
            assert "--- a/file" in f.read()
        os.unlink(result)

    @patch(f"{_GIT_MOD}._run_git")
    def test_uncommitted_changes(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = [
            _make_completed(stdout="same-head\n"),  # rev-parse HEAD (same)
            _make_completed(stdout="--- a/modified\n+++ b/modified\n"),  # diff HEAD
            _make_completed(stdout=""),  # ls-files --others
        ]

        result = _capture_git_diff("/tmp/ws", "same-head")
        assert result is not None
        with open(result) as f:
            assert "--- a/modified" in f.read()
        os.unlink(result)

    @patch(f"{_GIT_MOD}._run_git")
    def test_empty_diff(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = [
            _make_completed(stdout="same-head\n"),  # rev-parse HEAD
            _make_completed(stdout=""),  # diff HEAD (empty)
            _make_completed(stdout=""),  # ls-files --others (empty)
        ]

        result = _capture_git_diff("/tmp/ws", "same-head")
        assert result is None

    def test_empty_head_before(self) -> None:
        assert _capture_git_diff("/tmp/ws", "") is None

    @patch(f"{_GIT_MOD}._run_git")
    def test_untracked_files_included(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = [
            _make_completed(stdout="same-head\n"),  # rev-parse HEAD
            _make_completed(stdout=""),  # diff HEAD (no staged)
            _make_completed(stdout="newfile.py\n"),  # ls-files --others
            _make_completed(stdout="+++ new content\n"),  # diff --no-index
        ]

        result = _capture_git_diff("/tmp/ws", "same-head")
        assert result is not None
        with open(result) as f:
            assert "+++ new content" in f.read()
        os.unlink(result)


# ---------------------------------------------------------------------------
# GitRunnerProvider lifecycle tests
# ---------------------------------------------------------------------------


class TestGitRunnerProvider:
    """Tests for the GitRunnerProvider class."""

    def test_name(self) -> None:
        assert GitRunnerProvider().name == "git"

    @patch(f"{_GIT_MOD}.os.chdir")
    @patch(f"{_GIT_MOD}._prepare_git_workspace", return_value="abc123")
    @patch(f"{_GIT_MOD}.allocate_workspace")
    def test_pre_agent(
        self,
        mock_alloc: MagicMock,
        mock_prepare: MagicMock,
        mock_chdir: MagicMock,
    ) -> None:
        mock_alloc.return_value = RunnerContext(
            project_name="proj",
            workspace_dir="/tmp/ws",
            workspace_num=101,
        )

        provider = GitRunnerProvider()
        ctx = provider.pre_agent("proj", n=5, release=False)

        mock_alloc.assert_called_once_with("proj", n=5, release=False)
        mock_prepare.assert_called_once_with("/tmp/ws")
        mock_chdir.assert_called_once_with("/tmp/ws")
        assert ctx.head_before == "abc123"

    @patch(f"{_GIT_MOD}._capture_git_diff", return_value="/tmp/diff.patch")
    @patch(f"{_GIT_MOD}.release_workspace")
    def test_post_agent_with_release(
        self,
        mock_release: MagicMock,
        mock_diff: MagicMock,
    ) -> None:
        ctx = RunnerContext(
            project_file="/path/to/proj.gp",
            workspace_dir="/tmp/ws",
            workspace_num=101,
            checkout_target="main",
            should_release=True,
            head_before="abc123",
        )

        provider = GitRunnerProvider()
        result = provider.post_agent(ctx)

        mock_release.assert_called_once_with("/path/to/proj.gp", 101, "git-main")
        mock_diff.assert_called_once_with("/tmp/ws", "abc123")
        assert result.diff_path == "/tmp/diff.patch"
        assert result.meta == {"meta_workspace": "101"}

    @patch(f"{_GIT_MOD}._capture_git_diff", return_value=None)
    @patch(f"{_GIT_MOD}.release_workspace")
    def test_post_agent_without_release(
        self,
        mock_release: MagicMock,
        mock_diff: MagicMock,
    ) -> None:
        ctx = RunnerContext(
            project_file="/path/to/proj.gp",
            workspace_dir="/tmp/ws",
            workspace_num=5,
            checkout_target="feature",
            should_release=False,
            head_before="def456",
        )

        provider = GitRunnerProvider()
        result = provider.post_agent(ctx)

        mock_release.assert_not_called()
        assert result.diff_path is None
        assert result.meta == {"meta_workspace": "5"}


# ---------------------------------------------------------------------------
# Built-in registration test
# ---------------------------------------------------------------------------


class TestBuiltInRegistration:
    """Verify get_runner_providers() includes git as a built-in."""

    @patch(
        "sase.runner_provider.importlib.metadata.entry_points",
        return_value=[],
    )
    def test_git_present_with_no_entry_points(self, mock_eps: MagicMock) -> None:
        providers = get_runner_providers()
        assert "git" in providers
        assert isinstance(providers["git"], GitRunnerProvider)
