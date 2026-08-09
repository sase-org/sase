"""Tests for sase.axe.chop_script_runner."""

import os
import stat
import time
from pathlib import Path
from unittest.mock import patch


from sase.axe.chop_script_runner import (
    _compose_chop_subprocess_env,
    discover_chop_script,
    list_chop_scripts,
    run_chop_script,
    stream_chop_script,
)


def test_compose_chop_env_strips_agent_identity_without_extras() -> None:
    environ = {
        "PATH": "/bin",
        "SASE_AGENT": "1",
        "SASE_AGENT_NAME": "parent",
        "SASE_AGENT_PLANNED_NAME": "parent",
        "SASE_AGENT_AUTO_APPROVE": "1",
        "SASE_CHOP_NAME": "workflow_checks",
    }

    result = _compose_chop_subprocess_env(environ)

    assert result == {
        "PATH": "/bin",
        "SASE_CHOP_NAME": "workflow_checks",
    }
    assert environ["SASE_AGENT_NAME"] == "parent"


def test_compose_chop_env_applies_extras_after_scrubbing() -> None:
    result = _compose_chop_subprocess_env(
        {
            "SASE_AGENT_NAME": "parent",
            "SASE_AGENT_RETRY_HANDOFF": "old",
            "KEEP": "ambient",
        },
        {
            "SASE_AGENT_RETRY_HANDOFF": "current",
            "KEEP": "extra",
        },
    )

    assert result == {
        "SASE_AGENT_RETRY_HANDOFF": "current",
        "KEEP": "extra",
    }


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
        result = discover_chop_script("sase_chop_my_chop", [])
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
        result = discover_chop_script("sase_chop_my_chop", [])
        assert result == script

    def test_does_not_add_legacy_prefix(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_executable(bin_dir / "sase_chop_my_chop")
        monkeypatch.setenv("PATH", str(bin_dir))

        assert discover_chop_script("my_chop", []) is None

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

    def test_forwards_cwd_to_subprocess(self, tmp_path):
        """The cwd= kwarg is forwarded to subprocess.run so the child runs
        in a stable directory even when the parent's CWD is dangling."""
        cwd_dir = tmp_path / "stable"
        cwd_dir.mkdir()
        script = tmp_path / "my_chop"
        _make_executable(script)
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")

        with patch("sase.axe.chop_script_runner.subprocess.run") as mock_run:
            run_chop_script(script, str(ctx_file), cwd=str(cwd_dir))

        assert mock_run.call_args.kwargs["cwd"] == str(cwd_dir)

    def test_cwd_defaults_to_none(self, tmp_path):
        """When cwd= is not passed, subprocess.run receives cwd=None
        (preserving back-compatible inherit-parent-CWD behavior)."""
        script = tmp_path / "my_chop"
        _make_executable(script)
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")

        with patch("sase.axe.chop_script_runner.subprocess.run") as mock_run:
            run_chop_script(script, str(ctx_file))

        assert mock_run.call_args.kwargs["cwd"] is None


class TestStreamChopScript:
    """Tests for stream_chop_script."""

    def test_writes_stdout_to_log(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(script, "#!/bin/sh\necho hello\necho world")
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        result = stream_chop_script(script, str(ctx_file), log_path)

        assert result.returncode == 0
        assert result.timed_out is False
        assert result.pid is not None
        assert result.output_bytes > 0
        assert log_path.read_text() == "hello\nworld\n"

    def test_merges_stderr_into_log(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(script, "#!/bin/sh\necho out\necho err 1>&2")
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        stream_chop_script(script, str(ctx_file), log_path)

        contents = log_path.read_text()
        assert "out" in contents
        assert "err" in contents

    def test_propagates_env_and_cwd(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(
            script,
            "#!/bin/sh\necho HELLO=$HELLO\npwd",
        )
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"
        cwd_dir = tmp_path / "stable"
        cwd_dir.mkdir()

        stream_chop_script(
            script,
            str(ctx_file),
            log_path,
            env={"HELLO": "world"},
            cwd=str(cwd_dir),
        )

        contents = log_path.read_text()
        assert "HELLO=world" in contents
        assert str(cwd_dir) in contents

    def test_on_pid_callback_invoked(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(script)
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        seen: list[int] = []
        stream_chop_script(script, str(ctx_file), log_path, on_pid=seen.append)
        assert len(seen) == 1
        assert seen[0] > 0

    def test_timeout_kills_child_and_flags_timed_out(self, tmp_path):
        script = tmp_path / "my_chop"
        _make_executable(script, "#!/bin/sh\nsleep 5")
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        start = time.monotonic()
        result = stream_chop_script(script, str(ctx_file), log_path, timeout=0.5)
        elapsed = time.monotonic() - start

        assert result.timed_out is True
        # Should not wait the full 5-second sleep — kill must happen fast.
        assert elapsed < 3.0

    def test_log_visible_before_process_exit(self, tmp_path):
        """First output must reach the log file before the script exits."""
        script = tmp_path / "my_chop"
        _make_executable(
            script,
            "#!/bin/sh\necho first\nsleep 0.6\necho second",
        )
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        captured: dict[str, str | None] = {"mid_run": None}

        def watcher(pid: int) -> None:
            # Poll for the first line to appear in the log file before
            # the subprocess has had time to print the second line.
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if log_path.exists() and "first" in log_path.read_text():
                    captured["mid_run"] = log_path.read_text()
                    return
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

        result = stream_chop_script(script, str(ctx_file), log_path, on_pid=watcher)

        assert result.returncode == 0
        assert captured["mid_run"] is not None, (
            "expected first line to be readable from log before subprocess exit"
        )
        assert "first" in (captured["mid_run"] or "")
        assert "second" not in (captured["mid_run"] or "")

    def test_returncode_nonzero_reported(self, tmp_path: Path):
        script = tmp_path / "my_chop"
        _make_executable(script, "#!/bin/sh\nexit 3")
        ctx_file = tmp_path / "ctx.json"
        ctx_file.write_text("{}")
        log_path = tmp_path / "run.log"

        result = stream_chop_script(script, str(ctx_file), log_path)
        assert result.returncode == 3
        assert result.timed_out is False


class TestListChopScripts:
    """Tests for list_chop_scripts."""

    def test_deduplication(self, tmp_path, monkeypatch):
        d = tmp_path / "scripts"
        d.mkdir()
        _make_executable(d / "sase_chop_delta")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        _make_executable(bin_dir / "sase_chop_delta")
        monkeypatch.setenv("PATH", str(bin_dir))
        result = list_chop_scripts([str(d)])
        assert result.count("sase_chop_delta") == 1

    def test_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", "")
        result = list_chop_scripts([str(tmp_path)])
        assert result == []
