"""Startup helpers for the axe daemon process."""

import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path

from sase.agent.env_hygiene import (
    scrub_agent_identity_env,
    scrub_chop_context_env,
)

from . import state as axe_state
from .config import AxeConfig, AxeConfigError, load_axe_config
from .desired_state import write_desired_state
from .lock import AXE_LOCK_FD_ENV, AxeLifecycleLock, clear_lock_holder_pid
from ._process_guard import (
    AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    axe_lifecycle_blocked_in_tests,
)
from ._process_probe import get_pid_from_pid_files, probe_orchestrator
from ._process_types import AxeOrchestratorProbe, AxeStartResult


AXE_START_SOURCE_ENV = "SASE_AXE_START_SOURCE"
AXE_WEDGED_LOCK_GRACE_SECONDS_ENV = "SASE_AXE_WEDGED_LOCK_GRACE_SECONDS"
DEFAULT_WEDGED_LOCK_GRACE_SECONDS = 90.0
_WEDGED_LOCK_MARKER_FILENAME = "wedged_lifecycle_lock.json"
_WEDGED_LOCK_TERM_TIMEOUT_SECONDS = 5.0
_WEDGED_LOCK_KILL_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class _WedgedLockRecovery:
    """Resolution of a held lifecycle lock with no published daemon PID."""

    result: AxeStartResult | None = None
    retry_start: bool = False
    terminated_pid: int | None = None


def _compose_axe_daemon_env(
    environ: Mapping[str, str],
    *,
    desired_state_source: str = "axe start",
) -> dict[str, str]:
    """Return a system-service environment without agent or chop context."""
    env = dict(environ)
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    for name in tuple(env):
        if name.startswith("PYTEST_"):
            env.pop(name)
    env[AXE_START_SOURCE_ENV] = desired_state_source
    return env


def start_axe_daemon(
    config: AxeConfig | None = None,
    *,
    desired_state_source: str = "axe start",
    record_desired_state: bool = True,
) -> int | None:
    """Start axe as a background daemon process.

    Launches ``sase axe`` (orchestrator mode) as a detached subprocess.

    Args:
        config: Optional AxeConfig; loaded from disk if not provided.

    Returns:
        PID of the running process, or None if startup failed.
    """
    return start_axe_daemon_result(
        config,
        desired_state_source=desired_state_source,
        record_desired_state=record_desired_state,
    ).pid


def start_axe_daemon_result(
    config: AxeConfig | None = None,
    *,
    desired_state_source: str = "axe start",
    record_desired_state: bool = True,
    _allow_wedged_lock_recovery: bool = True,
) -> AxeStartResult:
    """Start axe as a background daemon process and return a detailed result."""
    if axe_lifecycle_blocked_in_tests():
        return AxeStartResult(
            status="blocked_in_tests",
            message=AXE_LIFECYCLE_TEST_BLOCK_MESSAGE,
        )

    daemon_cwd = Path(os.path.expanduser("~"))
    if not daemon_cwd.is_dir():
        return AxeStartResult(
            status="failed",
            message=(
                "Could not start axe because its daemon home/cwd is not "
                f"an existing directory: {daemon_cwd}"
            ),
        )

    if record_desired_state:
        write_desired_state("running", source=desired_state_source)

    existing_pid = get_pid_from_pid_files()
    if existing_pid is not None:
        _clear_wedged_lock_marker()
        return AxeStartResult(
            status="already_running",
            pid=existing_pid,
            message=f"Axe is already running (pid {existing_pid}).",
        )

    lifecycle_lock = _acquire_lifecycle_lock_for_start()
    if lifecycle_lock is None:
        existing_pid = get_pid_from_pid_files()
        if existing_pid is not None:
            _clear_wedged_lock_marker()
            return AxeStartResult(
                status="already_running",
                pid=existing_pid,
                message=f"Axe is already running (pid {existing_pid}).",
            )
        probe = probe_orchestrator()
        if probe.lock_held:
            recovery = _recover_wedged_lifecycle_lock(
                probe,
                allow_termination=_allow_wedged_lock_recovery,
            )
            if recovery.retry_start:
                return _retry_start_after_wedged_lock_recovery(
                    config,
                    desired_state_source=desired_state_source,
                    record_desired_state=record_desired_state,
                    terminated_pid=recovery.terminated_pid,
                )
            assert recovery.result is not None
            return recovery.result
        _clear_wedged_lock_marker()
        return AxeStartResult(
            status="failed",
            message="Timed out acquiring the axe lifecycle lock.",
        )

    _clear_wedged_lock_marker()
    handed_off = False
    process: subprocess.Popen[bytes] | None = None
    try:
        existing_pid = get_pid_from_pid_files()
        if existing_pid is not None:
            return AxeStartResult(
                status="already_running",
                pid=existing_pid,
                message=f"Axe is already running (pid {existing_pid}).",
            )

        if config is None:
            try:
                config = load_axe_config()
            except AxeConfigError as exc:
                return AxeStartResult(status="failed", message=str(exc))

        cmd = _build_axe_start_command(config)
        if cmd is None:
            return AxeStartResult(
                status="failed",
                message="Could not find a `sase` executable to start axe.",
            )

        log_dir = axe_state.axe_state_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "axe.log"

        env = _compose_axe_daemon_env(
            os.environ,
            desired_state_source=desired_state_source,
        )
        env[AXE_LOCK_FD_ENV] = str(lifecycle_lock.fd)
        with open(log_file, "a") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(lifecycle_lock.fd,),
                env=env,
                cwd=str(daemon_cwd),
            )
        handed_off = True
        lifecycle_lock.close_after_handoff()
    finally:
        if not handed_off:
            lifecycle_lock.release()

    if process is None:
        return AxeStartResult(status="failed", message="Failed to spawn axe.")
    pid = _wait_for_daemon_start(process)
    if pid is not None:
        return AxeStartResult(
            status="started",
            pid=pid,
            message=f"Axe started (pid {pid}).",
        )

    exit_code = process.poll()
    if exit_code is not None:
        return AxeStartResult(
            status="failed",
            message=f"Axe start process exited before publishing a PID (code {exit_code}).",
        )
    probe = probe_orchestrator()
    if probe.lock_held:
        recovery = _recover_wedged_lifecycle_lock(
            probe,
            allow_termination=_allow_wedged_lock_recovery,
        )
        if recovery.retry_start:
            return _retry_start_after_wedged_lock_recovery(
                config,
                desired_state_source=desired_state_source,
                record_desired_state=record_desired_state,
                terminated_pid=recovery.terminated_pid,
            )
        assert recovery.result is not None
        return recovery.result
    _clear_wedged_lock_marker()
    return AxeStartResult(
        status="failed",
        message="Timed out waiting for axe to publish its daemon PID.",
    )


def _acquire_lifecycle_lock_for_start(
    timeout: float = 15.0,
) -> AxeLifecycleLock | None:
    """Acquire the lifecycle lock, waiting through startup/shutdown races."""
    deadline = time.monotonic() + timeout
    while True:
        existing_pid = get_pid_from_pid_files()
        if existing_pid is not None:
            return None

        lifecycle_lock = AxeLifecycleLock.acquire(blocking=False)
        if lifecycle_lock is not None:
            return lifecycle_lock

        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


_EPHEMERAL_WORKSPACE_RE = re.compile(r"^sase_\d+$")


def _path_is_ephemeral_workspace(path: Path) -> bool:
    """Return True when *path* is inside a numbered SASE workspace clone."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return any(_EPHEMERAL_WORKSPACE_RE.fullmatch(part) for part in resolved.parts)


def _running_from_ephemeral_workspace() -> bool:
    """Return True when this process appears to be inside an agent workspace."""
    paths: list[Path] = [Path(sys.executable)]
    try:
        paths.append(Path.cwd())
    except OSError:
        pass
    if any(_path_is_ephemeral_workspace(path) for path in paths):
        return True
    return any(
        os.environ.get(name)
        for name in (
            "SASE_AGENT_NAME",
            "SASE_AGENT_PROJECT_FILE",
            "SASE_AGENT_TIMESTAMP",
        )
    )


def _resolve_primary_workspace_sase() -> str | None:
    """Resolve a non-ephemeral primary workspace ``sase`` executable."""
    try:
        from sase.bead.workspace import resolve_primary_workspace

        primary = resolve_primary_workspace()
    except Exception:
        return None
    if primary is None or _path_is_ephemeral_workspace(primary):
        return None
    candidate = primary / ".venv" / "bin" / "sase"
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_sase_executable(*, prefer_canonical: bool) -> str | None:
    """Find the best ``sase`` executable for launching long-lived daemons."""
    current_bin = Path(sys.executable).parent / "sase"
    current = str(current_bin) if current_bin.exists() else None
    path_sase = shutil.which("sase")

    candidates: list[str | None]
    if prefer_canonical:
        candidates = [
            str(Path.home() / ".local" / "bin" / "sase"),
            path_sase,
            _resolve_primary_workspace_sase(),
            current,
        ]
    else:
        candidates = [
            current,
            path_sase,
            str(Path.home() / ".local" / "bin" / "sase"),
        ]

    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate != path_sase and not candidate_path.exists():
            continue
        if prefer_canonical and _path_is_ephemeral_workspace(candidate_path):
            continue
        return str(candidate_path)
    return None


def should_reexec_axe_start_from_canonical() -> bool:
    """Return True when ``sase axe start`` should re-exec from a stable install."""
    if os.environ.get("SASE_AXE_CANONICALIZED"):
        return False
    return _running_from_ephemeral_workspace()


def canonical_axe_start_command() -> str | None:
    """Return a stable ``sase`` executable for axe daemon startup."""
    return _resolve_sase_executable(prefer_canonical=True)


def _build_axe_start_command(config: AxeConfig) -> list[str] | None:
    """Build the detached orchestrator command."""
    sase_cmd = _resolve_sase_executable(
        prefer_canonical=_running_from_ephemeral_workspace()
    )
    if sase_cmd is None:
        return None

    cmd = [
        sase_cmd,
        "axe",
        "start",
        "--max-hook-runners",
        str(config.max_hook_runners),
        "--max-agent-runners",
        str(config.max_agent_runners),
        "--zombie-timeout",
        str(config.zombie_timeout_seconds),
    ]
    if config.query:
        cmd.extend(["-q", config.query])
    return cmd


def _wait_for_daemon_start(
    process: subprocess.Popen[bytes],
    timeout: float = 15.0,
) -> int | None:
    """Wait for the spawned orchestrator to publish a live PID file."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = get_pid_from_pid_files()
        if pid is not None:
            return pid
        if process.poll() is not None:
            return None
        time.sleep(0.05)

    return get_pid_from_pid_files()


def _wedged_lock_marker_path() -> Path:
    return axe_state.axe_state_dir() / _WEDGED_LOCK_MARKER_FILENAME


def _read_wedged_lock_marker() -> tuple[float, int | None] | None:
    data = axe_state.read_json(_wedged_lock_marker_path())
    if not isinstance(data, dict):
        return None
    try:
        observed_at = float(data["observed_at_epoch"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isfinite(observed_at):
        return None
    raw_pid = data.get("lock_holder_pid")
    if raw_pid is None:
        holder_pid = None
    elif isinstance(raw_pid, int) and raw_pid > 0:
        holder_pid = raw_pid
    else:
        return None
    return observed_at, holder_pid


def _write_wedged_lock_marker(now: float, holder_pid: int | None) -> None:
    axe_state.atomic_write_json(
        _wedged_lock_marker_path(),
        {
            "observed_at_epoch": now,
            "lock_holder_pid": holder_pid,
        },
    )


def _clear_wedged_lock_marker() -> None:
    try:
        _wedged_lock_marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def _wedged_lock_grace_seconds() -> float:
    raw_value = os.environ.get(AXE_WEDGED_LOCK_GRACE_SECONDS_ENV)
    if raw_value is None:
        return DEFAULT_WEDGED_LOCK_GRACE_SECONDS
    try:
        value = float(raw_value)
    except ValueError:
        return DEFAULT_WEDGED_LOCK_GRACE_SECONDS
    if not isfinite(value) or value < 0:
        return DEFAULT_WEDGED_LOCK_GRACE_SECONDS
    return value


def _blocked_lock_result(
    probe: AxeOrchestratorProbe,
    *,
    detail: str,
) -> AxeStartResult:
    lock_holder = (
        f" by pid {probe.lock_holder_pid}" if probe.lock_holder_pid is not None else ""
    )
    return AxeStartResult(
        status="blocked",
        message=(
            f"Axe lifecycle lock is held{lock_holder}, but no live "
            f"orchestrator PID is published. {detail} Run `sase axe stop`; "
            "if the lock remains stuck, run `sase axe stop --force`."
        ),
    )


def _recover_wedged_lifecycle_lock(
    initial_probe: AxeOrchestratorProbe,
    *,
    allow_termination: bool,
) -> _WedgedLockRecovery:
    """Recover a lifecycle lock that remains unpublished beyond its grace."""
    now = time.time()
    holder_pid = initial_probe.lock_holder_pid
    marker = _read_wedged_lock_marker()
    if marker is None or marker[1] != holder_pid or now < marker[0]:
        _write_wedged_lock_marker(now, holder_pid)
        grace = _wedged_lock_grace_seconds()
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                initial_probe,
                detail=(
                    "Axe will retry recovery after the "
                    f"{grace:g}s startup grace period."
                ),
            )
        )

    observed_at, _marker_holder_pid = marker
    grace = _wedged_lock_grace_seconds()
    age = now - observed_at
    if age < grace or not allow_termination:
        remaining = max(0.0, grace - age)
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                initial_probe,
                detail=(
                    "Axe is waiting for the lock holder to publish its PID "
                    f"({remaining:.1f}s of startup grace remain)."
                ),
            )
        )

    published_pid = get_pid_from_pid_files()
    if published_pid is not None:
        _clear_wedged_lock_marker()
        return _WedgedLockRecovery(
            result=AxeStartResult(
                status="already_running",
                pid=published_pid,
                message=f"Axe is already running (pid {published_pid}).",
            )
        )

    probe = probe_orchestrator()
    if not probe.lock_held:
        _clear_wedged_lock_marker()
        return _WedgedLockRecovery(retry_start=True)
    if probe.lock_holder_pid != holder_pid:
        _write_wedged_lock_marker(now, probe.lock_holder_pid)
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                probe,
                detail=(
                    "The lock holder changed during recovery; its startup "
                    "grace period has been reset."
                ),
            )
        )
    if holder_pid is None:
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                probe,
                detail="The lock holder PID could not be resolved safely.",
            )
        )
    if holder_pid == os.getpid():
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                probe,
                detail="Recovery refused to signal the current process.",
            )
        )

    # Re-probe immediately before signaling so a legitimate slow starter that
    # just published its PID is never mistaken for a wedged process.
    published_pid = get_pid_from_pid_files()
    if published_pid is not None:
        _clear_wedged_lock_marker()
        return _WedgedLockRecovery(
            result=AxeStartResult(
                status="already_running",
                pid=published_pid,
                message=f"Axe is already running (pid {published_pid}).",
            )
        )

    from ._process_stop import terminate_process

    terminated = terminate_process(
        holder_pid,
        timeout=_WEDGED_LOCK_TERM_TIMEOUT_SECONDS,
        kill_timeout=_WEDGED_LOCK_KILL_TIMEOUT_SECONDS,
    )
    final_probe = probe_orchestrator()
    if not terminated.stopped or final_probe.lock_held:
        return _WedgedLockRecovery(
            result=_blocked_lock_result(
                final_probe,
                detail=f"Automatic recovery could not terminate pid {holder_pid}.",
            )
        )

    clear_lock_holder_pid()
    _clear_wedged_lock_marker()
    return _WedgedLockRecovery(
        retry_start=True,
        terminated_pid=holder_pid,
    )


def _retry_start_after_wedged_lock_recovery(
    config: AxeConfig | None,
    *,
    desired_state_source: str,
    record_desired_state: bool,
    terminated_pid: int | None,
) -> AxeStartResult:
    retried = start_axe_daemon_result(
        config,
        desired_state_source=desired_state_source,
        record_desired_state=record_desired_state,
        _allow_wedged_lock_recovery=False,
    )
    if terminated_pid is None:
        return retried

    _notify_wedged_lock_recovery(terminated_pid, retried.pid)
    return replace(
        retried,
        recovered_lock_holder_pid=terminated_pid,
        message=(
            f"Recovered wedged axe lifecycle lock held by pid "
            f"{terminated_pid}. {retried.message}"
        ).strip(),
    )


def _notify_wedged_lock_recovery(
    terminated_pid: int,
    started_pid: int | None,
) -> None:
    try:
        from sase.notifications.senders import notify_axe_lock_recovered

        notify_axe_lock_recovered(terminated_pid, started_pid)
    except Exception:
        # Process recovery is authoritative even if its audit notification
        # cannot be persisted in a damaged home.
        pass
