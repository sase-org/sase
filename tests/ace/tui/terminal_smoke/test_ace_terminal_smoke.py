"""Optional real-terminal smoke coverage for sase's TUI."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = [pytest.mark.slow, pytest.mark.terminal_smoke]

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_ace_cli_paints_patch_in_real_pty(tmp_path: Path) -> None:
    """Launch `sase tui` in a PTY and assert a decoded terminal grid."""
    pexpect = pytest.importorskip("pexpect")
    pyte = pytest.importorskip("pyte")

    _write_project(tmp_path, name="terminal_feature")
    child = pexpect.spawn(
        sys.executable,
        [
            "-m",
            "sase",
            "ace",
            '"terminal"',
            "-x",
            "-r",
            "0",
        ],
        cwd=str(_REPO_ROOT),
        dimensions=(40, 120),
        encoding="utf-8",
        codec_errors="replace",
        env=_terminal_env(tmp_path),
        timeout=20,
    )

    screen_output = ""
    try:
        child.expect("terminal_feature")
        screen_output = child.before + child.after
        child.send("q")
        child.expect(pexpect.EOF, timeout=10)
    finally:
        if child.isalive():
            child.terminate(force=True)
        child.close()

    assert child.exitstatus == 0
    assert "\x1b[" in screen_output

    screen = pyte.Screen(120, 40)
    stream = pyte.Stream(screen)
    stream.feed(screen_output)
    display = "\n".join(screen.display)

    assert "terminal_feature" in display
    assert "[R]" in display
    assert "Traceback" not in screen_output


def test_ace_cli_exports_svg_after_sigusr2_in_real_pty(tmp_path: Path) -> None:
    """Launch `sase tui` in a PTY and trigger the live SVG export handler."""
    if not hasattr(signal, "SIGUSR2"):
        pytest.skip("SIGUSR2 is not available on this platform")
    pexpect = pytest.importorskip("pexpect")

    request_dir = tmp_path / "screens"
    _write_project(tmp_path, name="terminal_screenshot_feature")
    env = _terminal_env(tmp_path)
    env["SASE_TUI_SCREENSHOT_DIR"] = str(request_dir)
    child = pexpect.spawn(
        sys.executable,
        [
            "-m",
            "sase",
            "ace",
            '"terminal"',
            "-x",
            "-r",
            "0",
        ],
        cwd=str(_REPO_ROOT),
        dimensions=(40, 120),
        encoding="utf-8",
        codec_errors="replace",
        env=env,
        timeout=20,
    )

    try:
        child.expect("terminal_screenshot_feature")
        os.kill(child.pid, signal.SIGUSR2)
        _wait_for_path(request_dir / "screen_1.done")
        child.send("q")
        child.expect(pexpect.EOF, timeout=10)
    finally:
        if child.isalive():
            child.terminate(force=True)
        child.close()

    assert child.exitstatus == 0
    svg = (request_dir / "screen_1.svg").read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "terminal_screenshot_feature" in svg


def test_sase_screenshot_cli_captures_png_with_tmux(tmp_path: Path) -> None:
    """Run the top-level screenshot command through tmux and rasterization."""
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not available")
    pytest.importorskip("resvg_py")

    feature_name = "terminal_screenshot_cli_feature"
    _write_project(tmp_path, name=feature_name)
    output = tmp_path / "shot.png"
    tmux_tmpdir = tmp_path / "tmux"
    tmux_tmpdir.mkdir()
    env = _terminal_env(tmp_path)
    env.pop("TMUX", None)
    env["TMUX_TMPDIR"] = str(tmux_tmpdir)

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sase",
                "screenshot",
                "-o",
                str(output),
                "--",
                f'"{feature_name}"',
            ],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
    finally:
        subprocess.run(
            ["tmux", "kill-server"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    assert result.returncode == 0, result.stderr
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert f"png={output}" in result.stdout
    assert "svg=" in result.stdout
    assert "sase_tmux_window=sase_tmux_1" in result.stdout


def _terminal_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = str(_REPO_ROOT / "src")
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env.update(
        {
            "COLUMNS": "120",
            "HOME": str(home),
            "LC_ALL": "C.UTF-8",
            "LINES": "40",
            "PYTHONPATH": pythonpath,
            "TERM": "xterm-256color",
            "TZ": "UTC",
        }
    )
    return env


def _write_project(home: Path, *, name: str) -> None:
    project_dir = home / ".sase" / "projects" / "terminal"
    project_dir.mkdir(parents=True)
    (project_dir / "terminal.sase").write_text(
        f"""# Terminal Smoke Project

## Patch

NAME: {name}
DESCRIPTION:
  Deterministic Patch for real-terminal ACE smoke coverage.
STATUS: Ready

---
"""
    )


def _wait_for_path(path: Path, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)  # sase-test-wait: real PTY cross-process file export
    raise AssertionError(f"timed out waiting for {path}")
