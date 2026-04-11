"""Tests for sase.memory.bootstrap."""

from pathlib import Path

from sase.memory.bootstrap import gather_project_context


class TestGatherProjectContext:
    def test_includes_project_name(self, tmp_path: Path) -> None:
        result = gather_project_context(str(tmp_path))
        assert tmp_path.name in result

    def test_includes_readme(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# My Project\nHello world")
        result = gather_project_context(str(tmp_path))
        assert "README.md" in result
        assert "Hello world" in result

    def test_includes_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"')
        result = gather_project_context(str(tmp_path))
        assert "pyproject.toml" in result
        assert 'name = "foo"' in result

    def test_directory_tree(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("pass")
        (tmp_path / "tests").mkdir()
        result = gather_project_context(str(tmp_path))
        assert "src/" in result
        assert "tests/" in result

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        result = gather_project_context(str(tmp_path))
        assert ".git" not in result

    def test_truncates_large_files(self, tmp_path: Path) -> None:
        large_content = "x" * 20_000
        (tmp_path / "README.md").write_text(large_content)
        result = gather_project_context(str(tmp_path))
        assert "truncated" in result
        # Should not contain the full content
        assert large_content not in result

    def test_empty_project(self, tmp_path: Path) -> None:
        result = gather_project_context(str(tmp_path))
        # Should still produce something (header + tree)
        assert "Project Context" in result

    def test_defaults_to_cwd(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:  # type: ignore[name-defined]  # noqa: F821
        monkeypatch.chdir(tmp_path)
        (tmp_path / "README.md").write_text("# Test")
        result = gather_project_context()
        assert "README.md" in result

    def test_skips_noisy_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".mypy_cache").mkdir()
        (tmp_path / "src").mkdir()
        result = gather_project_context(str(tmp_path))
        assert "__pycache__" not in result
        assert ".mypy_cache" not in result
        assert "src/" in result

    def test_multiple_key_files(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("readme")
        (tmp_path / "Makefile").write_text("all: build")
        (tmp_path / "Dockerfile").write_text("FROM python:3.12")
        result = gather_project_context(str(tmp_path))
        assert "README.md" in result
        assert "Makefile" in result
        assert "Dockerfile" in result
