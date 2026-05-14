"""Process helpers for daemon lifecycle management."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def process_is_live(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OverflowError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def executable_matches_metadata(pid: int, metadata: dict[str, Any]) -> bool:
    expected_raw = metadata.get("executable_path")
    if not isinstance(expected_raw, str) or not expected_raw:
        return True
    proc_exe = Path("/proc") / str(pid) / "exe"
    if not proc_exe.exists():
        return True
    try:
        actual = proc_exe.resolve(strict=True)
        expected = Path(expected_raw).expanduser().resolve(strict=False)
    except OSError:
        return True
    return actual == expected
