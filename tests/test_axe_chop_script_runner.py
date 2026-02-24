"""Tests for sase.axe.chop_script_runner."""

import os
import stat


from sase.axe.chop_script_runner import (
    discover_chop_script,
    list_chop_scripts,
    run_chop_script,
)


def _make_executable(path, content="#!/bin/sh\necho ok"):
    """Helper: write a script and make it executable."""
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestDiscoverChopScript:
    """Tests for discover_chop_script."""

    def test_finds_in_search_dir(self, tmp_path):
        d = tmp_path / "scripts"
        d.mkdir()
        script = d / "my_chop"
        _make_executable(script)
        result = discover_chop_script("my_chop", [str(d)])
        assert result == script

    def test_falls_back_to_path(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "sase_chop_my_chop"
        _make_executable(script)
        monkeypatch.setenv(
            "PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        )
        result = discover_chop_script("my_chop", [])
        assert result is not None
        assert result.name == "sase_chop_my_chop"

    def test_finds_in_sys_executable_bin_dir(self, tmp_path, monkeypatch):
        """Chop scripts next to sys.executable are found even without PATH."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_python = bin_dir / "python"
        fake_python.write_text("")
        script = bin_dir / "sase_chop_my_chop"
        _make_executable(script)
        monkeypatch.setattr(
            "sase.axe.chop_script_runner.sys.executable", str(fake_python)
        )
        monkeypatch.setenv("PATH", "")
        result = discover_chop_script("my_chop", [])
        assert result == script

    def test_returns_none_when_not_found(self, tmp_path):
        result = discover_chop_script("nonexistent", [str(tmp_path)])
        assert result is None


class TestRunChopScript:
    """Tests for run_chop_script."""

    def test_captures_stderr(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(script, "#!/bin/sh\necho err_msg >&2")
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        result = run_chop_script(script, str(ctx_file))
        assert "err_msg" in result.stderr


class TestListChopScripts:
    """Tests for list_chop_scripts."""

    def test_deduplication(self, tmp_path, monkeypatch):
        d = tmp_path / "scripts"
        d.mkdir()
        _make_executable(d / "delta")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_executable(bin_dir / "sase_chop_delta")
        monkeypatch.setenv("PATH", str(bin_dir))
        result = list_chop_scripts([str(d)])
        assert result.count("delta") == 1

    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", "")
        result = list_chop_scripts([str(tmp_path)])
        assert result == []
