"""Tests for sase.memory.reflect."""

from pathlib import Path
from unittest.mock import patch

from sase.memory.models import MemoryType
from sase.memory.reflect import (
    find_recent_chat_log,
    gather_reflection_context,
)
from sase.memory.repo import ensure_repo
from sase.memory.store import add


def _init_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        ensure_repo()
    return repo_path


def _patch_repo(repo_path: Path):
    return patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path)


class TestGatherReflectionContext:
    def test_includes_project_name(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_reflection_context(project="myproj")
        assert "myproj" in result

    def test_includes_existing_memories(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Test Conv",
                description="Use snake_case",
                memory_type=MemoryType.CONVENTION,
                body="Always use snake_case for variables.",
                project="myproj",
            )
            result = gather_reflection_context(project="myproj")
        assert "test_conv.md" in result
        assert "snake_case" in result

    def test_warns_no_duplicates(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            add(
                name="Existing",
                description="d",
                memory_type=MemoryType.FEEDBACK,
                body="x",
                project="proj",
            )
            result = gather_reflection_context(project="proj")
        assert "Do NOT create duplicates" in result

    def test_empty_repo(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_reflection_context(project="proj")
        assert "No memories exist" in result

    def test_no_repo(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "nonexistent"
        with patch("sase.memory.repo.MEMORY_REPO_PATH", fake_path):
            result = gather_reflection_context(project="proj")
        assert "not initialized" in result

    def test_includes_chat_log(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_reflection_context(
                project="proj",
                chat_log="User asked about testing approach.",
            )
        assert "Recent Chat Session" in result
        assert "testing approach" in result

    def test_truncates_long_chat_log(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        long_log = "x" * 60_000
        with _patch_repo(repo):
            result = gather_reflection_context(
                project="proj",
                chat_log=long_log,
            )
        assert "truncated" in result
        assert long_log not in result

    def test_no_chat_section_when_none(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path)
        with _patch_repo(repo):
            result = gather_reflection_context(project="proj")
        assert "Recent Chat Session" not in result


class TestFindRecentChatLog:
    def test_no_chats_dir(self, tmp_path: Path) -> None:
        with patch("sase.memory.reflect.Path.home", return_value=tmp_path):
            result = find_recent_chat_log(project="proj")
        assert result is None

    def test_finds_project_chat(self, tmp_path: Path) -> None:
        chats_dir = tmp_path / ".sase" / "chats" / "proj"
        chats_dir.mkdir(parents=True)
        (chats_dir / "session1.md").write_text("First session log")
        with patch("sase.memory.reflect.Path.home", return_value=tmp_path):
            result = find_recent_chat_log(project="proj")
        assert result == "First session log"

    def test_finds_most_recent(self, tmp_path: Path) -> None:
        import os
        import time

        chats_dir = tmp_path / ".sase" / "chats" / "proj"
        chats_dir.mkdir(parents=True)
        old = chats_dir / "old.md"
        old.write_text("old content")
        # Ensure different mtime
        time.sleep(0.05)
        new = chats_dir / "new.md"
        new.write_text("new content")
        os.utime(new, (new.stat().st_mtime + 10, new.stat().st_mtime + 10))
        with patch("sase.memory.reflect.Path.home", return_value=tmp_path):
            result = find_recent_chat_log(project="proj")
        assert result == "new content"

    def test_empty_chats_dir(self, tmp_path: Path) -> None:
        chats_dir = tmp_path / ".sase" / "chats"
        chats_dir.mkdir(parents=True)
        with patch("sase.memory.reflect.Path.home", return_value=tmp_path):
            result = find_recent_chat_log(project="proj")
        assert result is None
