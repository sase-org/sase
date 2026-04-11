"""Tests for sase.memory.inject."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.inject import build_injection, _get_system_contents
from sase.memory.repo import ensure_repo


@pytest.fixture
def memory_repo(tmp_path: Path) -> Path:
    """Provide a temporary memory repo path."""
    repo_path = tmp_path / "memory"
    with patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path):
        yield repo_path


def _patch_repo(repo_path: Path):
    """Return a combined patch for both repo and inject modules."""
    return patch("sase.memory.repo.MEMORY_REPO_PATH", repo_path)


class TestGetSystemContents:
    def test_empty_when_no_repo(self, tmp_path: Path) -> None:
        fake = tmp_path / "nonexistent"
        with patch("sase.memory.repo.MEMORY_REPO_PATH", fake):
            assert _get_system_contents() == []

    def test_empty_when_no_system_files(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            assert _get_system_contents() == []

    def test_global_system_files(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            sys_dir = memory_repo / "global" / "system"
            (sys_dir / "prefs.md").write_text(
                "---\nname: Prefs\ndescription: User prefs\n"
                "type: convention\ncreated: 2026-01-01\n---\n\nBe concise."
            )

            result = _get_system_contents()

        assert len(result) == 1
        assert result[0][0] == "global/system/prefs.md"
        assert "Be concise." in result[0][1]

    def test_project_system_files(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            proj_sys = memory_repo / "projects" / "myproj" / "system"
            proj_sys.mkdir(parents=True)
            (proj_sys / "arch.md").write_text("Architecture notes")

            result = _get_system_contents(project="myproj")

        assert len(result) == 1
        assert result[0][0] == "projects/myproj/system/arch.md"

    def test_both_global_and_project(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            global_sys = memory_repo / "global" / "system"
            (global_sys / "global_note.md").write_text("Global note")

            proj_sys = memory_repo / "projects" / "myproj" / "system"
            proj_sys.mkdir(parents=True)
            (proj_sys / "proj_note.md").write_text("Project note")

            result = _get_system_contents(project="myproj")

        assert len(result) == 2
        paths = [r[0] for r in result]
        assert "global/system/global_note.md" in paths
        assert "projects/myproj/system/proj_note.md" in paths

    def test_skips_empty_files(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            global_sys = memory_repo / "global" / "system"
            (global_sys / "empty.md").write_text("")
            (global_sys / "notempty.md").write_text("content")

            result = _get_system_contents()

        assert len(result) == 1
        assert result[0][0] == "global/system/notempty.md"


class TestBuildInjection:
    def test_empty_when_no_repo(self, tmp_path: Path) -> None:
        fake = tmp_path / "nonexistent"
        with patch("sase.memory.repo.MEMORY_REPO_PATH", fake):
            assert build_injection() == ""

    def test_includes_filetree_header(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            result = build_injection()

        assert "## Agent Memory" in result
        assert "### Filetree" in result

    def test_includes_system_contents(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            global_sys = memory_repo / "global" / "system"
            (global_sys / "conv.md").write_text("Use type hints everywhere")

            result = build_injection()

        assert "### System Context (Always Loaded)" in result
        assert "#### global/system/conv.md" in result
        assert "Use type hints everywhere" in result

    def test_project_scoped(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            proj_sys = memory_repo / "projects" / "sase" / "system"
            proj_sys.mkdir(parents=True)
            (proj_sys / "arch.md").write_text("src layout project")

            result = build_injection(project="sase")

        assert "#### projects/sase/system/arch.md" in result
        assert "src layout project" in result

    def test_token_budget_truncation(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            global_sys = memory_repo / "global" / "system"
            # Create a file larger than a tiny token budget
            (global_sys / "big.md").write_text("x" * 2000)

            result = build_injection(max_system_tokens=100)

        assert "token budget reached" in result

    def test_no_system_section_when_no_files(self, memory_repo: Path) -> None:
        with _patch_repo(memory_repo):
            ensure_repo()
            result = build_injection()

        assert "### Filetree" in result
        assert "### System Context" not in result
