"""Tests for sase.memory.sync."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.repo import ensure_repo
from sase.memory.sync import (
    SyncConflictError,
    add_remote,
    get_remote_url,
    remove_remote,
    sync,
)


@pytest.fixture
def memory_repo(tmp_path: Path) -> Path:
    """Provide a temporary memory repo path."""
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        ensure_repo()
        yield repo_path


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare git repo to act as a remote."""
    remote_path = tmp_path / "remote.git"
    remote_path.mkdir()
    subprocess.run(
        ["git", "init", "--bare"],
        cwd=remote_path,
        capture_output=True,
        check=True,
    )
    return remote_path


class TestAddRemote:
    def test_adds_new_remote(self, memory_repo: Path, bare_remote: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote), name="origin")
            url = get_remote_url("origin")
        assert url == str(bare_remote)

    def test_updates_existing_remote(
        self, memory_repo: Path, bare_remote: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other.git"
        other.mkdir()
        subprocess.run(
            ["git", "init", "--bare"], cwd=other, capture_output=True, check=True
        )
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote), name="origin")
            add_remote(str(other), name="origin")
            url = get_remote_url("origin")
        assert url == str(other)

    def test_custom_name(self, memory_repo: Path, bare_remote: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote), name="backup")
            assert get_remote_url("backup") == str(bare_remote)
            assert get_remote_url("origin") is None

    def test_raises_when_no_repo(self, tmp_path: Path) -> None:
        repo_path = tmp_path / "nonexistent"
        with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
            with pytest.raises(RuntimeError, match="not initialized"):
                add_remote("https://example.com/repo.git")


class TestRemoveRemote:
    def test_removes_remote(self, memory_repo: Path, bare_remote: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote))
            remove_remote("origin")
            assert get_remote_url("origin") is None

    def test_raises_when_not_configured(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            with pytest.raises(ValueError, match="not configured"):
                remove_remote("origin")


class TestGetRemoteUrl:
    def test_returns_none_when_no_remote(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            assert get_remote_url() is None

    def test_returns_url(self, memory_repo: Path, bare_remote: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote))
            assert get_remote_url() == str(bare_remote)


class TestSync:
    def test_first_sync_pushes(self, memory_repo: Path, bare_remote: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote))
            msg = sync()
        assert "first sync" in msg

        # Verify remote has the commit
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=bare_remote,
            capture_output=True,
            text=True,
        )
        assert "Initialize memory repository" in result.stdout

    def test_sync_pulls_and_pushes(
        self, memory_repo: Path, bare_remote: Path, tmp_path: Path
    ) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            add_remote(str(bare_remote))
            sync()

        # Clone elsewhere, make a change, push
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", str(bare_remote), str(clone)],
            capture_output=True,
            check=True,
        )
        (clone / "new_memory.md").write_text("hello from clone")
        subprocess.run(["git", "add", "-A"], cwd=clone, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add memory from clone"],
            cwd=clone,
            capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=clone, capture_output=True, check=True)

        # Sync original — should pull the new file
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            msg = sync()
        assert "Synced" in msg
        assert (memory_repo / "new_memory.md").is_file()

    def test_sync_raises_when_no_remote(self, memory_repo: Path) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            with pytest.raises(ValueError, match="not configured"):
                sync()

    def test_sync_conflict_raises(
        self, memory_repo: Path, bare_remote: Path, tmp_path: Path
    ) -> None:
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            # Create a file locally and push
            (memory_repo / "conflict.md").write_text("local version 1")
            subprocess.run(["git", "add", "-A"], cwd=memory_repo, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "local"],
                cwd=memory_repo,
                capture_output=True,
            )
            add_remote(str(bare_remote))
            sync()

        # Clone elsewhere, modify same file, push
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", str(bare_remote), str(clone)],
            capture_output=True,
            check=True,
        )
        (clone / "conflict.md").write_text("remote version")
        subprocess.run(["git", "add", "-A"], cwd=clone, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "remote change"],
            cwd=clone,
            capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=clone, capture_output=True, check=True)

        # Modify same file locally (divergent change)
        with patch("sase.memory.repo.MEMORY_REPO_PATH", memory_repo):
            (memory_repo / "conflict.md").write_text("local version 2")
            subprocess.run(["git", "add", "-A"], cwd=memory_repo, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "local diverge"],
                cwd=memory_repo,
                capture_output=True,
            )

            with pytest.raises(SyncConflictError):
                sync()

        # Verify rebase was aborted (repo is clean)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=memory_repo,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == ""
