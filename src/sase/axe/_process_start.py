"""Startup helpers for the axe daemon process."""

import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

from sase.agent.env_hygiene import (
    scrub_agent_identity_env,
    scrub_chop_context_env,
)

from .config import AxeConfig, AxeConfigError, load_axe_config
from .desired_state import write_desired_state
from .lock import AXE_LOCK_FD_ENV, AxeLifecycleLock
from .state import AXE_STATE_DIR
from ._process_probe import get_axe_pid, get_pid_from_pid_files, probe_orchestrator
from ._process_types import AxeStartResult


AXE_START_SOURCE_ENV = "SASE_AXE_START_SOURCE"


def _compose_axe_daemon_env(
    environ: Mapping[str, str],
    *,
    desired_state_source: str = "start",
) -> dict[str, str]:
    """Return a system-service environment without agent or chop context."""
    env = dict(environ)
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    env[AXE_START_SOURCE_ENV] = desired_state_source
    return env


def start_axe_daemon(
    config: AxeConfig | None = None,
    *,
    desired_state_source: str = "start",
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
    desired_state_source: str = "start",
    record_desired_state: bool = True,
) -> AxeStartResult:
    """Start axe as a background daemon process and return a detailed result."""
    if record_desired_state:
        write_desired_state("running", source=desired_state_source)

    existing_pid = get_axe_pid()
    if existing_pid is not None:
        return AxeStartResult(
            status="already_running",
            pid=existing_pid,
            message=f"Axe is already running (pid {existing_pid}).",
        )

    lifecycle_lock = _acquire_lifecycle_lock_for_start()
    if lifecycle_lock is None:
        existing_pid = get_axe_pid()
        if existing_pid is not None:
            return AxeStartResult(
                status="already_running",
                pid=existing_pid,
                message=f"Axe is already running (pid {existing_pid}).",
            )
        probe = probe_orchestrator()
        if probe.lock_held:
            lock_holder = (
                f" by pid {probe.lock_holder_pid}"
                if probe.lock_holder_pid is not None
                else ""
            )
            return AxeStartResult(
                status="blocked",
                message=(
                    f"Axe lifecycle lock is held{lock_holder}, but no live "
                    "orchestrator PID is published. Run `sase axe stop`; if "
                    "the lock remains stuck, run `sase axe stop --force`."
                ),
            )
        return AxeStartResult(
            status="failed",
            message="Timed out acquiring the axe lifecycle lock.",
        )

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

        log_dir = AXE_STATE_DIR / "logs"
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
                cwd=os.path.expanduser("~"),
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
        lock_holder = (
            f" by pid {probe.lock_holder_pid}"
            if probe.lock_holder_pid is not None
            else ""
        )
        return AxeStartResult(
            status="blocked",
            message=(
                f"Axe lifecycle lock is held{lock_holder}, but no live "
                "orchestrator PID is published. Run `sase axe stop`; if the "
                "lock remains stuck, run `sase axe stop --force`."
            ),
        )
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
        existing_pid = get_axe_pid()
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
        pid = get_axe_pid()
        if pid is not None:
            return pid
        if process.poll() is not None:
            return None
        time.sleep(0.05)

    return get_axe_pid()
