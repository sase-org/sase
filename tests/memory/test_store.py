"""Tests for sase.memory.store."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.models import MemoryType
from sase.memory.repo import ensure_repo
from sase.memory.store import add, list_memories, rm, show


@pytest.fixture
def memory_repo(tmp_path: Path) -> Path:
    """Provide an initialized temporary memory repo."""
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        ensure_repo()
    return repo_path


def _patch_repo(repo_path: Path):
    return patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path)


class TestAdd:
    def test_creates_file(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            filepath = add(
                name="Testing Approach",
                description="Prefer integration tests",
                memory_type=MemoryType.FEEDBACK,
                body="Use real DB.",
                project="sase",
            )
        assert filepath.is_file()
        assert filepath.name == "testing_approach.md"
        assert "projects/sase" in str(filepath)

    def test_global_memory(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            filepath = add(
                name="Dark Mode",
                description="User prefers dark themes",
                memory_type=MemoryType.CONVENTION,
                body="Always suggest dark themes.",
            )
        assert "global" in str(filepath)

    def test_system_flag(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            filepath = add(
                name="Core Arch",
                description="Architecture overview",
                memory_type=MemoryType.ARCHITECTURE,
                body="Uses src layout.",
                project="sase",
                system=True,
            )
        assert "/system/" in str(filepath)

    def test_duplicate_raises(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            add(
                name="Dup",
                description="d",
                memory_type=MemoryType.DECISION,
                body="x",
                project="test",
            )
            with pytest.raises(FileExistsError, match="already exists"):
                add(
                    name="Dup",
                    description="d",
                    memory_type=MemoryType.DECISION,
                    body="y",
                    project="test",
                )

    def test_auto_commits(self, memory_repo: Path) -> None:
        import subprocess

        with _patch_repo(memory_repo):
            add(
                name="Commit Test",
                description="d",
                memory_type=MemoryType.PITFALL,
                body="content",
                project="myproj",
            )
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=memory_repo,
            capture_output=True,
            text=True,
        )
        assert "memory: add Commit Test" in result.stdout


class TestShow:
    def test_show_existing(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            add(
                name="Show Me",
                description="test show",
                memory_type=MemoryType.REFERENCE,
                body="Look here.",
                project="proj",
            )
            mem = show("Show Me", project="proj")
        assert mem.name == "Show Me"
        assert mem.body == "Look here."

    def test_show_not_found(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            with pytest.raises(FileNotFoundError, match="not found"):
                show("Nonexistent", project="proj")


class TestListMemories:
    def test_list_all(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            add(
                name="Global One",
                description="g1",
                memory_type=MemoryType.CONVENTION,
                body="g1 body",
            )
            add(
                name="Proj One",
                description="p1",
                memory_type=MemoryType.FEEDBACK,
                body="p1 body",
                project="alpha",
            )
            memories = list_memories()
        assert len(memories) == 2
        paths = [rel for rel, _ in memories]
        assert any("global" in p for p in paths)
        assert any("alpha" in p for p in paths)

    def test_list_project_filter(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            add(
                name="A",
                description="a",
                memory_type=MemoryType.DECISION,
                body="a",
                project="alpha",
            )
            add(
                name="B",
                description="b",
                memory_type=MemoryType.DECISION,
                body="b",
                project="beta",
            )
            memories = list_memories(project="alpha")
        assert len(memories) == 1
        assert "alpha" in memories[0][0]

    def test_list_empty(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            assert list_memories() == []


class TestRm:
    def test_removes_file(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            filepath = add(
                name="Remove Me",
                description="d",
                memory_type=MemoryType.PITFALL,
                body="x",
                project="proj",
            )
            assert filepath.is_file()
            rm("Remove Me", project="proj")
            assert not filepath.is_file()

    def test_rm_not_found(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            with pytest.raises(FileNotFoundError, match="not found"):
                rm("Ghost", project="proj")

    def test_rm_auto_commits(self, memory_repo: Path) -> None:
        import subprocess

        with _patch_repo(memory_repo):
            add(
                name="Gone",
                description="d",
                memory_type=MemoryType.FEEDBACK,
                body="x",
                project="proj",
            )
            rm("Gone", project="proj")
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=memory_repo,
            capture_output=True,
            text=True,
        )
        assert "memory: remove Gone" in result.stdout
