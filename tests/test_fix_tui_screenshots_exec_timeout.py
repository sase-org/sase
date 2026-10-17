"""Wall-clock budget tests for governed visual pytest execution."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import threading
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


def _drain_with_outer_bound(
    proc: subprocess.Popen[bytes],
    log: io.BytesIO,
    *,
    timeout_seconds: float,
    grace_seconds: float,
    outer_seconds: float = 5.0,
) -> int:
    """Keep a regression from hanging pytest if the helper loses its bound."""
    done = threading.Event()
    result: list[int] = []
    errors: list[BaseException] = []

    def drain() -> None:
        try:
            result.append(
                _drain_child_output(
                    proc,
                    log,
                    mirror=False,
                    timeout_seconds=timeout_seconds,
                    grace_seconds=grace_seconds,
                )
            )
        except BaseException as exc:  # surface worker errors in the test thread
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=drain, daemon=True)
    worker.start()
    if not done.wait(outer_seconds):
        _kill_owned_group(proc)
        done.wait(2.0)
        worker.join(timeout=1.0)
        raise AssertionError(
            f"subprocess drain exceeded its {outer_seconds:g}s outer safety bound"
        )
    worker.join(timeout=1.0)
    if errors:
        raise errors[0]
    assert result
    return result[0]


def _kill_owned_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _wait_for_file(path: Path, *, timeout_seconds: float = 3.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            time.sleep(0.01)  # sase-test-wait: poll until child writes readiness file
    raise AssertionError(f"child did not create readiness file {path}")


def _process_is_live(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return False
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return False
    fields = stat[close_paren + 1 :].split()
    return bool(fields) and fields[0] not in {"Z", "X"}


def _spawn_term_ignoring_descendant(
    tmp_path: Path, *, leader_sleeps: bool
) -> tuple[subprocess.Popen[bytes], int]:
    descendant_ready = tmp_path / "descendant-ready"
    leader_ready = tmp_path / "leader-ready"
    child_code = (
        "import os, pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    leader_code = (
        "import pathlib, subprocess, sys, time\n"
        f"child_code = {child_code!r}\n"
        "ready = pathlib.Path(sys.argv[1])\n"
        "leader_ready = pathlib.Path(sys.argv[2])\n"
        "child = subprocess.Popen([sys.executable, '-c', child_code, str(ready)])\n"
        "deadline = time.monotonic() + 4\n"
        "while not ready.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(.01)\n"
        "assert ready.exists(), 'descendant did not install its signal handler'\n"
        "leader_ready.write_text(str(child.pid))\n"
    )
    if leader_sleeps:
        leader_code += "time.sleep(30)\n"
    proc = _spawn(
        [
            sys.executable,
            "-c",
            leader_code,
            str(descendant_ready),
            str(leader_ready),
        ]
    )
    try:
        descendant_pid = int(_wait_for_file(leader_ready))
    except BaseException:
        _kill_owned_group(proc)
        raise
    return proc, descendant_pid


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


def test_early_pipe_eof_does_not_exceed_timeout(tmp_path: Path) -> None:
    ready = tmp_path / "pipe-closed"
    proc = _spawn(
        [
            sys.executable,
            "-c",
            "import os, sys, time; "
            "os.close(1); os.close(2); "
            "open(sys.argv[1], 'w').write('ready'); "
            "time.sleep(30)",
            str(ready),
        ]
    )
    try:
        _wait_for_file(ready)
        log = io.BytesIO()
        start = time.monotonic()
        code = _drain_with_outer_bound(
            proc, log, timeout_seconds=0.25, grace_seconds=0.1
        )
        assert code == TIMEOUT_EXIT_CODE
        assert time.monotonic() - start < 2.0
        assert proc.poll() is not None
        assert b"recapture budget expired" in log.getvalue()
    finally:
        _kill_owned_group(proc)


def test_timeout_kills_term_ignoring_descendant_after_leader_exits(
    tmp_path: Path,
) -> None:
    proc, descendant_pid = _spawn_term_ignoring_descendant(tmp_path, leader_sleeps=True)
    try:
        log = io.BytesIO()
        code = _drain_with_outer_bound(
            proc, log, timeout_seconds=0.25, grace_seconds=0.1
        )
        assert code == TIMEOUT_EXIT_CODE
        assert proc.returncode == -signal.SIGTERM
        assert not _process_is_live(descendant_pid)
    finally:
        _kill_owned_group(proc)


def test_timeout_kills_descendant_when_leader_already_exited(
    tmp_path: Path,
) -> None:
    proc, descendant_pid = _spawn_term_ignoring_descendant(
        tmp_path, leader_sleeps=False
    )
    try:
        # The descendant inherited the output pipe, so the already-exited
        # leader cannot produce EOF until the group is cleaned up.
        proc.wait(timeout=3.0)
        assert proc.returncode == 0
        assert _process_is_live(descendant_pid)
        log = io.BytesIO()
        code = _drain_with_outer_bound(
            proc, log, timeout_seconds=0.25, grace_seconds=0.1
        )
        assert code == TIMEOUT_EXIT_CODE
        assert not _process_is_live(descendant_pid)
    finally:
        _kill_owned_group(proc)


def test_terminate_process_tree_reaps_exited_child() -> None:
    proc = _spawn([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    _terminate_process_tree(proc, grace_seconds=0.5)
    assert proc.poll() is not None
