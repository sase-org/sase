"""Discovery and execution of external chop scripts.

Chop scripts are standalone executables named exactly by configuration.
Resolution never adds or strips a ``sase_chop_`` prefix.
"""

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def discover_chop_script(name: str, search_dirs: list[str]) -> Path | None:
    """Find an executable chop script by name.

    Searches *search_dirs* for an executable file matching *name*, then checks
    the bin directory of the running Python interpreter, then performs an
    exact-name ``PATH`` lookup.

    Args:
        name: Chop name to look up.
        search_dirs: Directories to search (in order).

    Returns:
        Path to the executable, or ``None`` if not found.
    """
    for d in search_dirs:
        candidate = Path(d) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    # Check the bin directory next to the running Python interpreter.
    # This ensures chop scripts installed as entry points in the same
    # virtualenv are found even when PATH symlinks are broken (e.g.
    # during a reinstall).
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate

    # Fallback: look for the exact configured executable on PATH.
    on_path = shutil.which(name)
    if on_path is not None:
        return Path(on_path)

    return None


def run_chop_script(
    script_path: Path,
    context_file: str,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a chop script with the given context file.

    Args:
        script_path: Path to the executable script.
        context_file: Path to the JSON context file.
        timeout: Optional timeout in seconds.
        env: Extra environment variables to inject into the subprocess.
        cwd: Working directory for the subprocess. When ``None``, the child
            inherits the parent's CWD, which can be dangling if the daemon
            outlived the directory it was launched from.

    Returns:
        The completed process result.
    """
    subprocess_env: dict[str, str] | None = None
    if env:
        subprocess_env = dict(os.environ)
        subprocess_env.update(env)

    return subprocess.run(
        [str(script_path), "--context", str(context_file)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=subprocess_env,
        cwd=cwd,
    )


@dataclass
class _StreamedScriptResult:
    """Outcome of a streamed chop script execution.

    ``returncode`` is the subprocess exit code, or ``None`` if the process was
    killed (e.g. on timeout) without ever reporting one. ``output_bytes`` is
    the number of bytes appended to ``log_path`` during this run, useful for
    history finalization without re-statting the file.
    """

    returncode: int | None
    pid: int | None
    output_bytes: int
    timed_out: bool


def stream_chop_script(
    script_path: Path,
    context_file: str,
    log_path: Path,
    *,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    on_pid: Callable[[int], None] | None = None,
) -> _StreamedScriptResult:
    """Execute a chop script, streaming combined stdout+stderr to ``log_path``.

    The script's stdout and stderr are merged (``stderr=STDOUT``) and pumped
    through a pipe so output reaches the log file before the subprocess
    exits. ``on_pid`` is invoked synchronously once with the child PID so
    callers can record it in run-history metadata immediately.

    On timeout the process is killed and ``timed_out=True`` is returned;
    ``returncode`` may be ``None`` if the kill happened before the OS recorded
    an exit status.
    """
    subprocess_env: dict[str, str] | None = None
    if env:
        subprocess_env = dict(os.environ)
        subprocess_env.update(env)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab", buffering=0)

    try:
        proc = subprocess.Popen(
            [str(script_path), "--context", str(context_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=subprocess_env,
            cwd=cwd,
            bufsize=0,
            # Start a new process group so timeout-kill can take down
            # grandchildren (e.g. a ``sleep`` invoked by the chop script)
            # without leaking orphaned processes that keep the stdout
            # pipe open and stall the pump thread.
            start_new_session=True,
        )
    except OSError:
        log_file.close()
        raise

    bytes_written = 0
    bytes_lock = threading.Lock()

    assert proc.stdout is not None
    stdout_fd = proc.stdout.fileno()

    def pump() -> None:
        nonlocal bytes_written
        try:
            while True:
                chunk = os.read(stdout_fd, 65536)
                if not chunk:
                    break
                log_file.write(chunk)
                with bytes_lock:
                    bytes_written += len(chunk)
        except (OSError, ValueError):
            # ValueError covers writes to ``log_file`` after the main thread
            # closed it — possible if ``pump_thread.join`` timed out because
            # a detached grandchild kept the pipe open past parent cleanup.
            # Without it the daemon would crash with an unhandled traceback
            # and drop the tail bytes silently.
            pass

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()

    if on_pid is not None:
        # Invoke the PID callback *after* the pump thread is live so
        # observers (e.g. a TUI poller) can already see output drained
        # to the log file while the subprocess is still running.
        try:
            on_pid(proc.pid)
        except Exception:
            # Best-effort: PID recording errors must not abort the run.
            pass

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Kill the whole process group so descendants (e.g. a ``sleep``
        # spawned by the chop script) don't keep the stdout pipe open.
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    # Give the pump a chance to drain any final bytes before we close the
    # log file. The pipe is closed by the subprocess's exit, so the read1
    # loop will see EOF quickly.
    pump_thread.join(timeout=5)
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except OSError:
            pass
    log_file.close()

    with bytes_lock:
        final_bytes = bytes_written

    return _StreamedScriptResult(
        returncode=proc.returncode,
        pid=proc.pid,
        output_bytes=final_bytes,
        timed_out=timed_out,
    )


def list_chop_scripts(search_dirs: list[str]) -> list[str]:
    """List all available chop scripts.

    Scans *search_dirs* for executables by their bare filename and ``$PATH``
    for legacy ``sase_chop_*`` executables as a discovery convenience.
    Returned names are always full executable names.

    Args:
        search_dirs: Directories to scan.

    Returns:
        Sorted list of unique chop script names.
    """
    names: set[str] = set()

    # Scan configured directories
    for d in search_dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            if entry.is_file() and os.access(entry, os.X_OK):
                names.add(entry.name)

    # Scan PATH for sase_chop_* executables
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            try:
                is_file = entry.is_file()
            except OSError:
                continue
            if (
                is_file
                and entry.name.startswith("sase_chop_")
                and os.access(entry, os.X_OK)
            ):
                names.add(entry.name)

    return sorted(names)
