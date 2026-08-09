"""Optional real-terminal smoke coverage for the ACE TUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


pytestmark = [pytest.mark.slow, pytest.mark.terminal_smoke]

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_ace_cli_paints_patch_in_real_pty(tmp_path: Path) -> None:
    """Launch `sase ace` in a PTY and assert a decoded terminal grid."""
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
