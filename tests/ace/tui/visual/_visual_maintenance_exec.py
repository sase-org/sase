"""Governed pytest execution and capture verification for visual maintenance."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Any, BinaryIO

from tests.ace.tui.visual._visual_maintenance_baseline import (
    default_ace_root,
    default_pager_root,
)
from tests.ace.tui.visual._visual_maintenance_manifest import posix_relative
from tests.ace.tui.visual._visual_maintenance_types import (
    GoldenBaseline,
    MaintenanceError,
    MaintenanceHooks,
)


def build_run_pytest_command(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    ace_root: Path,
    pager_root: Path,
) -> list[str]:
    """Return the governed visual runner command for candidate capture."""
    command = [
        sys.executable,
        str(repo_root / "tools" / "run_pytest"),
        "visual",
        "--sase-visual-capture-dir",
        str(capture_dir),
        "--sase-visual-capture-run-id",
        run_id,
        "--sase-visual-capture-scope",
        scope,
        "--sase-visual-capture-ace-root",
        posix_relative(ace_root, repo_root),
        "--sase-visual-capture-pager-root",
        posix_relative(pager_root, repo_root),
        *pytest_args,
    ]
    return command


WORKERS_ENV_VAR = "SASE_PYTEST_WORKERS"


# Exit code reported when the recapture wall-clock budget expires while a
# governed child is still running. It mirrors ``timeout(1)``; pytest itself
# only exits 0-5, so this value unambiguously means "we stopped the child".
TIMEOUT_EXIT_CODE = 124

# Grace between SIGTERM and SIGKILL when stopping an over-budget process
# tree. Short enough to preserve the CI report-upload margin, long enough
# for xdist workers to exit cleanly and release the suite admission lease.
TERMINATE_GRACE_SECONDS = 10.0

# A SIGKILLed direct child should be reapable promptly. Keep this wait bounded
# as well: an uninterruptible kernel wait must not turn timeout cleanup into an
# unbounded wait.
_POST_KILL_REAP_SECONDS = 1.0


def run_governed_visual_pytest(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
    ace_root: Path,
    pager_root: Path,
    workers: int | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    """Invoke ``tools/run_pytest visual`` with candidate capture enabled.

    When *workers* is set, the child runs with ``SASE_PYTEST_WORKERS=<n>``
    in a copy of the process environment. ``None`` keeps the governed
    default.

    When *timeout_seconds* is set, a quiet or hung child cannot block past
    the remaining recapture budget: the owned process group is terminated
    (SIGTERM, then SIGKILL after a bounded grace), partial logs are kept,
    and :data:`TIMEOUT_EXIT_CODE` is returned. ``None`` keeps the previous
    unbounded behavior for first-pass capture and update mode.
    """
    command = build_run_pytest_command(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        ace_root=ace_root,
        pager_root=pager_root,
    )
    child_env: Mapping[str, str] | None = None
    if workers is not None:
        base = dict(os.environ if environ is None else environ)
        base[WORKERS_ENV_VAR] = str(workers)
        child_env = base
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(child_env) if child_env is not None else None,
            start_new_session=True,
        )
        assert proc.stdout is not None
        try:
            return _drain_child_output(
                proc,
                log,
                timeout_seconds=timeout_seconds,
            )
        except KeyboardInterrupt:
            _terminate_process_tree(proc)
            raise


def _drain_child_output(
    proc: subprocess.Popen[bytes],
    log: BinaryIO,
    *,
    mirror: bool = True,
    timeout_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    grace_seconds: float = TERMINATE_GRACE_SECONDS,
) -> int:
    """Mirror child output to *log* until EOF; enforce *timeout_seconds*.

    Returns the child exit code, or :data:`TIMEOUT_EXIT_CODE` when the
    budget expired first. On expiry the owned process group is stopped so
    no xdist child survives, partial output already read is preserved, and
    a note is appended to the log.
    """
    assert proc.stdout is not None
    stdout_fd = proc.stdout.fileno()
    deadline = None if timeout_seconds is None else clock() + timeout_seconds
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining: float | None = None
            if deadline is not None:
                remaining = deadline - clock()
                if remaining <= 0:
                    return _timeout_kill(proc, log, grace_seconds=grace_seconds)
            ready = selector.select(timeout=remaining)
            if not ready:
                return _timeout_kill(proc, log, grace_seconds=grace_seconds)
            # os.read issues a single raw read: unlike BufferedReader.read,
            # which loops until its buffer is full or EOF, it returns the
            # bytes already available, so a quiet child cannot stall the
            # deadline check below.
            chunk = os.read(stdout_fd, 65536)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
            if mirror:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    finally:
        selector.close()
    if deadline is None:
        return int(proc.wait())
    remaining = deadline - clock()
    if remaining <= 0:
        return _timeout_kill(proc, log, grace_seconds=grace_seconds)
    try:
        return int(proc.wait(timeout=remaining))
    except subprocess.TimeoutExpired:
        return _timeout_kill(proc, log, grace_seconds=grace_seconds)


def _timeout_kill(
    proc: subprocess.Popen[bytes],
    log: BinaryIO,
    *,
    grace_seconds: float,
) -> int:
    """Stop an over-budget child, keep partial logs, report the timeout."""
    _terminate_process_tree(proc, grace_seconds=grace_seconds)
    _drain_remaining(proc, log)
    note = (
        f"\n[sase] recapture budget expired; terminated child pid {proc.pid} "
        f"and its process group (exit {TIMEOUT_EXIT_CODE})\n"
    ).encode()
    log.write(note)
    log.flush()
    return TIMEOUT_EXIT_CODE


def _drain_remaining(proc: subprocess.Popen[bytes], log: BinaryIO) -> None:
    """Append whatever the dead child left in its stdout pipe to *log*.

    Reads non-blocking so a pipe holder that escaped the process-group
    kill cannot stall the run; whatever is unread stays unread.
    """
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    try:
        os.set_blocking(fd, False)
    except (OSError, ValueError):
        pass
    try:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            log.write(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            os.set_blocking(fd, True)
        except (OSError, ValueError):
            pass
    log.flush()


def _terminate_process_tree(
    proc: subprocess.Popen[bytes],
    grace_seconds: float = TERMINATE_GRACE_SECONDS,
) -> None:
    """Terminate the owned process group with a bounded grace/kill fallback.

    The child starts in its own session, so signalling the group also stops
    xdist workers it spawned. The lease and locks they hold are released by
    the kernel when the holders die.
    """
    process_group_id = proc.pid
    _signal_process_group(process_group_id, signal.SIGTERM)
    grace_deadline = time.monotonic() + max(0.0, grace_seconds)

    while True:
        # poll() reaps the leader when it has exited. Its descendants can
        # still hold the output pipe or maintenance lock, so their state is
        # checked separately from the leader's return code.
        proc.poll()
        group_live = _process_group_has_live_members(process_group_id)
        if proc.returncode is not None and not group_live:
            return
        remaining = grace_deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))

    # The leader may have exited on SIGTERM while a descendant ignored it.
    # Escalate against the owned process group, not just the Popen leader.
    if _process_group_has_live_members(process_group_id):
        _signal_process_group(process_group_id, signal.SIGKILL)

    reap_deadline = time.monotonic() + _POST_KILL_REAP_SECONDS
    while _process_group_has_live_members(process_group_id):
        remaining = reap_deadline - time.monotonic()
        if remaining <= 0:
            # A second group signal is harmless if the first one already
            # finished its work, and still targets only this owned group.
            _signal_process_group(process_group_id, signal.SIGKILL)
            break
        time.sleep(min(0.05, remaining))

    try:
        proc.wait(timeout=max(0.0, reap_deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        # Cover a process that raced with the first group scan or has not yet
        # acted on SIGKILL. Both attempts remain bounded.
        _signal_process_group(process_group_id, signal.SIGKILL)
        try:
            proc.wait(timeout=_POST_KILL_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _signal_process_group(process_group_id: int, signum: int) -> None:
    """Signal one owned process group, tolerating a group that already exited."""
    try:
        os.killpg(process_group_id, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _process_group_has_live_members(process_group_id: int) -> bool:
    """Return whether the group has work left, ignoring exited zombies.

    Linux exposes each process's group and state in ``/proc/<pid>/stat``.
    Zombie and dead entries no longer hold pipes or locks and should not keep
    the grace period alive. On systems without procfs, killpg(..., 0) provides
    the best available group-existence check.
    """
    proc_root = Path("/proc")
    try:
        entries = os.scandir(proc_root)
    except OSError:
        return _process_group_exists(process_group_id)

    with entries:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                stat = Path(entry.path, "stat").read_text(encoding="ascii")
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError:
                # If procfs is restricted, fall back to the portable group
                # existence check rather than falsely declaring it empty.
                return _process_group_exists(process_group_id)
            close_paren = stat.rfind(")")
            if close_paren < 0:
                continue
            fields = stat[close_paren + 1 :].split()
            if len(fields) < 3:
                continue
            try:
                member_group = int(fields[2])
            except ValueError:
                continue
            if member_group == process_group_id and fields[0] not in {"Z", "X"}:
                return True
    return False


def _process_group_exists(process_group_id: int) -> bool:
    """Best-effort group check for platforms without readable procfs."""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_pytest(
    hooks: MaintenanceHooks,
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
    workers: int | None = None,
    timeout_seconds: float | None = None,
) -> int:
    runner = hooks.run_pytest or run_governed_visual_pytest
    return runner(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        log_path=log_path,
        ace_root=default_ace_root(repo_root),
        pager_root=default_pager_root(repo_root),
        workers=workers,
        timeout_seconds=timeout_seconds,
    )


def assert_pruning_safe(inventory: Any, baseline: GoldenBaseline) -> None:
    """Refuse orphan deletion when a full run produced no captures for a root."""
    if not inventory.pruning_allowed:
        return
    if not inventory.captures:
        raise MaintenanceError(
            "full inventory produced no screenshot captures; refusing stale "
            "deletion so a failed capture plugin cannot wipe goldens"
        )
    captured_roots = {record.root_identity for record in inventory.captures}
    for identity in ("ace", "pager"):
        has_goldens = any(
            state.root_identity == identity for state in baseline.files.values()
        )
        if has_goldens and identity not in captured_roots:
            raise MaintenanceError(
                f"full inventory captured no {identity} screenshots; "
                "refusing stale deletion for that root"
            )
