"""Tests for sase.memory.repo."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.repo import (
    auto_commit,
    ensure_repo,
    get_filetree,
    get_repo_path,
    repo_exists,
)


@pytest.fixture
def memory_repo(tmp_path: Path) -> Path:
    """Provide a temporary memory repo path."""
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        yield repo_path


class TestEnsureRepo:
    def test_creates_repo(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            path = ensure_repo()
        assert path == memory_repo
        assert (memory_repo / ".git").is_dir()
        assert (memory_repo / "global" / "system").is_dir()
        assert (memory_repo / "projects").is_dir()
        assert (memory_repo / "README.md").is_file()

    def test_idempotent(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            path = ensure_repo()
        assert path == memory_repo

    def test_initial_commit_exists(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=memory_repo,
            capture_output=True,
            text=True,
        )
        assert "Initialize memory repository" in result.stdout


class TestRepoExists:
    def test_false_when_not_initialized(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            assert not repo_exists()

    def test_true_after_init(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            assert repo_exists()


class TestAutoCommit:
    def test_commits_changes(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            (memory_repo / "test.md").write_text("hello")
            auto_commit("test commit")

        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=memory_repo,
            capture_output=True,
            text=True,
        )
        assert "test commit" in result.stdout

    def test_noop_when_nothing_changed(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            # Count commits before
            result1 = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=memory_repo,
                capture_output=True,
                text=True,
            )
            auto_commit("should be noop")
            result2 = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=memory_repo,
                capture_output=True,
                text=True,
            )
            assert result1.stdout.strip() == result2.stdout.strip()

    def test_raises_when_no_repo(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            with pytest.raises(RuntimeError, match="not initialized"):
                auto_commit("fail")


class TestGetFiletree:
    def test_empty_repo(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            tree = get_filetree()
        assert "global/" in tree
        assert "projects/" in tree

    def test_project_filter(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            ensure_repo()
            # Create two project dirs
            (memory_repo / "projects" / "alpha" / "system").mkdir(parents=True)
            (memory_repo / "projects" / "alpha" / "system" / "arch.md").write_text("x")
            (memory_repo / "projects" / "beta").mkdir(parents=True)
            (memory_repo / "projects" / "beta" / "notes.md").write_text("y")

            tree = get_filetree(project="alpha")
        assert "alpha/" in tree
        assert "beta" not in tree


class TestGetRepoPath:
    def test_returns_path(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            assert get_repo_path() == memory_repo
