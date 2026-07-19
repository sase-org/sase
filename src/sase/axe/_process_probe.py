"""PID and lifecycle-lock probing for the axe daemon."""

from pathlib import Path

from sase.ace.hooks.processes import is_process_running

from .lock import (
    clear_lock_holder_pid,
    is_lifecycle_lock_held,
    read_lock_holder_pid,
)
from .orchestrator import ORCHESTRATOR_PID_FILE
from ._process_types import AxeOrchestratorProbe


def is_axe_running() -> bool:
    """Check if the axe orchestrator is currently running.

    Returns:
        True if axe is running, False otherwise.
    """
    return probe_orchestrator().running


def get_axe_pid() -> int | None:
    """Get the PID of the running axe orchestrator.

    Reconciles the lifecycle lock with the orchestrator PID file and the
    legacy global PID file. The lock is authoritative for liveness; this
    function returns the best known live PID when one can be resolved.

    Returns:
        PID if running, None otherwise.
    """
    return probe_orchestrator().running_pid


def get_pid_from_pid_files() -> int | None:
    """Return a live PID from PID files without consulting the lifecycle lock."""
    orchestrator_pid = _read_pid_path(ORCHESTRATOR_PID_FILE)

    from .state import read_pid_file

    legacy_pid = read_pid_file()
    if orchestrator_pid is not None and is_process_running(orchestrator_pid):
        return orchestrator_pid
    if legacy_pid is not None and is_process_running(legacy_pid):
        return legacy_pid
    return None


def probe_orchestrator(*, cleanup: bool = True) -> AxeOrchestratorProbe:
    """Probe axe orchestrator liveness from lock and PID-file state."""
    lock_held = is_lifecycle_lock_held()
    lock_holder_pid = read_lock_holder_pid() if lock_held else None
    orchestrator_pid = _read_pid_path(ORCHESTRATOR_PID_FILE)

    from .state import read_pid_file, remove_pid_file

    legacy_pid = read_pid_file()

    lock_holder_running = lock_holder_pid is not None and is_process_running(
        lock_holder_pid
    )
    orchestrator_running = orchestrator_pid is not None and is_process_running(
        orchestrator_pid
    )
    legacy_running = legacy_pid is not None and is_process_running(legacy_pid)

    running_pid: int | None = None
    if lock_holder_running:
        running_pid = lock_holder_pid
    elif orchestrator_running:
        running_pid = orchestrator_pid
    elif legacy_running:
        running_pid = legacy_pid

    if cleanup:
        if orchestrator_pid is not None and not orchestrator_running:
            _remove_orchestrator_pid_file(expected_pid=orchestrator_pid)
        if legacy_pid is not None and not legacy_running:
            remove_pid_file()
        if not lock_held and read_lock_holder_pid() is not None:
            clear_lock_holder_pid()

    return AxeOrchestratorProbe(
        lock_held=lock_held,
        lock_holder_pid=lock_holder_pid,
        orchestrator_pid_file_pid=orchestrator_pid,
        legacy_pid=legacy_pid,
        running_pid=running_pid,
    )


def _read_pid_path(path: Path) -> int | None:
    """Read an integer PID from *path*."""
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def _remove_orchestrator_pid_file(*, expected_pid: int) -> None:
    """Remove the orchestrator PID file if it still names *expected_pid*."""
    if _read_pid_path(ORCHESTRATOR_PID_FILE) != expected_pid:
        return
    try:
        ORCHESTRATOR_PID_FILE.unlink()
    except OSError:
        pass


def cleanup_pid_files(*, stopped_pid: int | None = None) -> None:
    """Remove stale or owned PID files after a stop attempt.

    A concurrently-started orchestrator may replace its PID file after the
    stopped process releases the lifecycle lock. Preserve that file whenever
    it names a different live process.
    """
    from .state import remove_pid_file

    current_pid = _read_pid_path(ORCHESTRATOR_PID_FILE)
    if current_pid is not None and (
        current_pid == stopped_pid or not is_process_running(current_pid)
    ):
        _remove_orchestrator_pid_file(expected_pid=current_pid)
    remove_pid_file()
