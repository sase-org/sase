"""Tests for sase.memory.defrag."""

from pathlib import Path
from unittest.mock import patch

from sase.memory.defrag import gather_defrag_context
from sase.memory.models import MemoryType
from sase.memory.repo import ensure_repo
from sase.memory.store import add


def _init_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        ensure_repo()
    return repo_path


def _patch_repo(repo_path: Path):
    return patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path)


class TestGatherDefragContext:
    def test_includes_project_name(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_defrag_context(project="myproj")
        assert "myproj" in result

    def test_no_repo(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "nonexistent"
        with patch("sase.memory.repo.MEMORY_REPO_PATH", fake_path):
            result = gather_defrag_context(project="proj")
        assert "not initialized" in result

    def test_empty_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_defrag_context(project="proj")
        assert "No memories found" in result
        assert "nothing to defragment" in result

    def test_includes_memory_content(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Test Conv",
                description="Use snake_case everywhere",
                memory_type=MemoryType.CONVENTION,
                body="Always use snake_case for variable names.",
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "Test Conv" in result
        assert "Use snake_case everywhere" in result
        assert "snake_case for variable names" in result

    def test_groups_by_type(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Conv1",
                description="d1",
                memory_type=MemoryType.CONVENTION,
                body="b1",
                project="proj",
            )
            add(
                name="Pit1",
                description="d2",
                memory_type=MemoryType.PITFALL,
                body="b2",
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "convention (1 files)" in result
        assert "pitfall (1 files)" in result

    def test_shows_total_count(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="A",
                description="a",
                memory_type=MemoryType.DECISION,
                body="a",
                project="proj",
            )
            add(
                name="B",
                description="b",
                memory_type=MemoryType.FEEDBACK,
                body="b",
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "Total memories:** 2" in result

    def test_shows_statistics(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Stat Test",
                description="d",
                memory_type=MemoryType.ARCHITECTURE,
                body="some content here",
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "Total files: 1" in result
        assert "Total content size:" in result

    def test_flags_large_files(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        large_body = "\n".join(f"line {i}" for i in range(60))
        with _patch_repo(repo):
            add(
                name="Big File",
                description="d",
                memory_type=MemoryType.ARCHITECTURE,
                body=large_body,
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "Large files (>50 lines)" in result

    def test_no_large_files_section_when_small(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Small",
                description="d",
                memory_type=MemoryType.CONVENTION,
                body="short",
                project="proj",
            )
            result = gather_defrag_context(project="proj")
        assert "Large files" not in result
