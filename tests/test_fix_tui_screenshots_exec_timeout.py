"""Wall-clock budget tests for governed visual pytest execution."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from tests.ace.tui.visual._visual_maintenance_exec import (
    TIMEOUT_EXIT_CODE,
    _drain_child_output,
    _terminate_process_tree,
)


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def test_silent_child_killed_at_timeout(tmp_path: Path) -> None:
    proc = _spawn([sys.executable, "-c", "import time; time.sleep(30)"])
    log_path = tmp_path / "silent.log"
    start = time.monotonic()
    with log_path.open("wb") as log:
        code = _drain_child_output(
            proc, log, mirror=False, timeout_seconds=0.5, grace_seconds=0.5
        )
    elapsed = time.monotonic() - start
    assert code == TIMEOUT_EXIT_CODE
    assert elapsed < 10.0
    assert proc.poll() is not None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "recapture budget expired" in text


def test_descendant_killed_with_process_group(tmp_path: Path) -> None:
    child_script = (
        "import subprocess, sys, time; "
        "grandchild = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(30)']); "
        "print(f'grandchild={grandchild.pid}', flush=True); "
        "time.sleep(30)"
    )
    proc = _spawn([sys.executable, "-c", child_script])
    log_path = tmp_path / "tree.log"
    with log_path.open("wb") as log:
        code = _drain_child_output(
            proc, log, mirror=False, timeout_seconds=1.0, grace_seconds=0.5
        )
    assert code == TIMEOUT_EXIT_CODE
    assert proc.poll() is not None
    grandchild_pid: int | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("grandchild="):
            grandchild_pid = int(line.split("=", 1)[1])
    assert grandchild_pid is not None
    with_deadline = time.monotonic() + 5.0
    while time.monotonic() < with_deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)  # sase-test-wait: poll until timeout-killed grandchild reaped
    else:
        raise AssertionError(f"grandchild {grandchild_pid} survived the timeout kill")


def test_term_ignoring_child_needs_kill_fallback(tmp_path: Path) -> None:
    proc = _spawn(
        [
            sys.executable,
            "-c",
            "import signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(30)",
        ]
    )
    log_path = tmp_path / "fallback.log"
    start = time.monotonic()
    with log_path.open("wb") as log:
        code = _drain_child_output(
            proc, log, mirror=False, timeout_seconds=0.5, grace_seconds=0.5
        )
    elapsed = time.monotonic() - start
    assert code == TIMEOUT_EXIT_CODE
    assert elapsed < 10.0
    assert proc.poll() is not None
    assert proc.returncode == -signal.SIGKILL


def test_partial_output_preserved_on_timeout(tmp_path: Path) -> None:
    proc = _spawn(
        [
            sys.executable,
            "-c",
            "import time; print('partial-line', flush=True); time.sleep(30)",
        ]
    )
    log_path = tmp_path / "partial.log"
    with log_path.open("wb") as log:
        code = _drain_child_output(
            proc, log, mirror=False, timeout_seconds=0.5, grace_seconds=0.5
        )
    assert code == TIMEOUT_EXIT_CODE
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "partial-line" in text
    assert "recapture budget expired" in text


def test_fast_child_unaffected_by_timeout(tmp_path: Path) -> None:
    proc = _spawn([sys.executable, "-c", "print('quick')"])
    log_path = tmp_path / "quick.log"
    with log_path.open("wb") as log:
        code = _drain_child_output(
            proc, log, mirror=False, timeout_seconds=30.0, grace_seconds=0.5
        )
    assert code == 0
    assert "quick" in log_path.read_text(encoding="utf-8", errors="replace")


def test_unbounded_drain_keeps_previous_behavior(tmp_path: Path) -> None:
    proc = _spawn([sys.executable, "-c", "print('hello')"])
    buffer = io.BytesIO()
    code = _drain_child_output(proc, buffer, mirror=False, timeout_seconds=None)
    assert code == 0
    assert b"hello" in buffer.getvalue()


def test_terminate_process_tree_reaps_exited_child() -> None:
    proc = _spawn([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    _terminate_process_tree(proc, grace_seconds=0.5)
    assert proc.poll() is not None
