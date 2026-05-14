"""Runtime start, stop, and lock repair actions for the local SASE daemon."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.integrations._daemon_lifecycle_config import (
    prepare_daemon_launch as default_prepare_daemon_launch,
)
from sase.integrations._daemon_lifecycle_inspection import inspect_daemon
from sase.integrations._daemon_lifecycle_process import (
    executable_matches_metadata,
    process_is_live,
    terminate_process as default_terminate_process,
)
from sase.integrations._daemon_lifecycle_types import (
    DEFAULT_STOP_TIMEOUT_SECONDS,
    KillFn,
    PopenFactory,
    SleepFn,
    DaemonInspection,
    DaemonLaunch,
    DaemonLifecycleError,
)
from sase.integrations._daemon_lifecycle_values import int_value, positive_float


def run_daemon_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = subprocess.Popen,
    sleep: SleepFn = time.sleep,
    prepare_daemon_launch: Callable[
        [argparse.Namespace], DaemonLaunch
    ] = default_prepare_daemon_launch,
    background_start_waiter: Callable[
        [DaemonLaunch, subprocess.Popen[Any], SleepFn], DaemonInspection
    ]
    | None = None,
    terminate_process: Callable[
        [subprocess.Popen[Any]], None
    ] = default_terminate_process,
) -> int:
    wait = background_start_waiter or wait_for_background_start
    launch = prepare_daemon_launch(args)
    if launch.foreground:
        print("Starting SASE daemon in the foreground.")
        proc = popen(launch.argv)
        try:
            return int(proc.wait())
        except KeyboardInterrupt:
            terminate_process(proc)
            return 130

    launch.paths.run_root.mkdir(parents=True, exist_ok=True)
    log_path = launch.paths.run_root / "daemon.log"
    print(f"Starting SASE daemon in the background. Log: {log_path}")
    with open(log_path, "ab") as log_file:
        proc = popen(
            launch.argv,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    inspection = wait(launch, proc, sleep)
    if inspection.state == "running":
        if inspection.rpc and inspection.rpc.get("available"):
            print("SASE daemon started; local RPC health is available.")
        else:
            print(
                "SASE daemon started; ownership metadata is available. "
                "Local RPC health is unavailable until the daemon transport is ready."
            )
        return 0
    raise DaemonLifecycleError(inspection.message)


def run_daemon_stop(
    args: argparse.Namespace,
    *,
    kill: KillFn = os.kill,
    sleep: SleepFn = time.sleep,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
    process_is_live: Callable[[int], bool] = process_is_live,
    executable_matches_metadata: Callable[
        [int, dict[str, Any]], bool
    ] = executable_matches_metadata,
) -> int:
    inspection = inspect_daemon(args)
    if inspection.state == "stopped":
        print("SASE daemon is not running.")
        return 0
    if inspection.state != "running" or inspection.metadata is None:
        raise DaemonLifecycleError(
            f"refusing to stop daemon from {inspection.state} metadata: "
            f"{inspection.message}"
        )

    pid = int_value(inspection.metadata.get("pid"))
    if pid is None:
        raise DaemonLifecycleError("refusing to stop daemon with missing pid")
    if not executable_matches_metadata(pid, inspection.metadata):
        raise DaemonLifecycleError(
            f"refusing to signal pid {pid}; executable does not match metadata"
        )

    kill(pid, signal.SIGTERM)
    timeout = positive_float(
        getattr(args, "stop_timeout", None),
        DEFAULT_STOP_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_is_live(pid):
            print(f"Stopped SASE daemon pid {pid}.")
            return 0
        sleep(0.1)
    raise DaemonLifecycleError(
        f"sent SIGTERM to daemon pid {pid}, but it is still running"
    )


def repair_stale_lock(
    args: argparse.Namespace,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> dict[str, Any]:
    inspection = inspect_daemon(args)
    if inspection.state != "stale":
        raise DaemonLifecycleError(
            f"refusing stale-lock repair from {inspection.state} daemon state: "
            f"{inspection.message}"
        )
    try:
        from sase.integrations._daemon_lifecycle_inspection import lock_file_is_held

        lock_held = lock_file_is_held(inspection.lock_path)
    except Exception as exc:
        raise DaemonLifecycleError(
            f"could not verify daemon lock ownership: {exc}"
        ) from exc
    if lock_held is not False:
        raise DaemonLifecycleError(
            f"refusing stale-lock repair because {inspection.lock_path} "
            "may still be held"
        )

    removed: list[str] = []
    skipped: list[str] = []
    for path in (
        inspection.paths.metadata_path,
        inspection.lock_path,
        inspection.paths.socket_path,
    ):
        if path == inspection.paths.socket_path and not _is_under(
            path, inspection.paths.run_root
        ):
            skipped.append(str(path))
            continue
        if not _is_under(path, inspection.paths.run_root):
            skipped.append(str(path))
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DaemonLifecycleError(
                f"failed to remove stale daemon runtime file {path}: {exc}"
            ) from exc
        removed.append(str(path))
    return {
        "state": "repaired",
        "action": "remove_stale_lock",
        "risk": "runtime_only",
        "removed": removed,
        "skipped": skipped,
        "message": "removed stale daemon runtime lock state",
    }


def wait_for_background_start(
    launch: DaemonLaunch,
    proc: subprocess.Popen[Any],
    sleep: SleepFn,
    *,
    inspect_daemon: Callable[[argparse.Namespace], DaemonInspection] = inspect_daemon,
) -> DaemonInspection:
    deadline = time.monotonic() + launch.startup_timeout_seconds
    last = DaemonInspection(
        state="stopped",
        paths=launch.paths,
        message="daemon did not publish ownership metadata yet",
    )
    args = argparse.Namespace(
        sase_home=str(launch.paths.sase_home),
        run_root=str(launch.paths.run_root),
        socket_path=str(launch.paths.socket_path),
    )
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            return DaemonInspection(
                state="stopped",
                paths=launch.paths,
                message=f"daemon exited before startup completed with code {exit_code}",
            )
        last = inspect_daemon(args)
        if last.state == "running":
            return last
        sleep(0.1)
    return last


def _is_under(path: os.PathLike[str] | str, parent: os.PathLike[str] | str) -> bool:
    try:
        return (
            Path(path)
            .resolve(strict=False)
            .is_relative_to(Path(parent).resolve(strict=False))
        )
    except OSError:
        return False
