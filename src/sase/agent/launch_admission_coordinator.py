"""Detached launch-admission coordinator process.

The coordinator is started after approval when waits remain. It is not a proc
shell: it lives beside the launch-request bundle and acknowledges startup with
a JSON marker before supervising remaining units.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from sase.agent.env_hygiene import scrub_agent_identity_env, scrub_chop_context_env
from sase.agent.launch_admission import (
    COORDINATOR_ENV,
    COORDINATOR_LOG_FILENAME,
    START_ACK_TIMEOUT_SECONDS,
    STARTED_FILENAME,
    admission_dir,
    install_coordinator_signal_flag,
    run_coordinator_in_bundle,
)
from sase.agent.launch_request_types import LaunchRequestError

_ACK_POLL_SECONDS = 0.05
_PID_WAIT_SECONDS = 5.0


def start_detached_coordinator(response_dir: Path) -> int:
    """Spawn the coordinator grandchild and wait for its startup acknowledgement."""

    root = admission_dir(response_dir)
    root.mkdir(parents=True, exist_ok=True)
    started = root / STARTED_FILENAME
    if started.is_file() and _coordinator_alive(root):
        return _sidecar_pid(root)
    env = os.environ.copy()
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    env[COORDINATOR_ENV] = "1"
    log_path = root / COORDINATOR_LOG_FILENAME
    with log_path.open("ab") as log_file:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.agent.launch_admission_coordinator",
                str(response_dir),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    error = _wait_for_start_ack(started, child)
    if error is not None:
        _terminate(child)
        raise LaunchRequestError("dispatch_failed", str(response_dir), error)
    return int(child.pid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sase.agent.launch_admission_coordinator")
    parser.add_argument("response_dir")
    args = parser.parse_args(argv)
    response_dir = Path(args.response_dir).expanduser()
    cancelled = install_coordinator_signal_flag()
    run_coordinator_in_bundle(response_dir, cancelled=cancelled)
    return 0


def _wait_for_start_ack(started: Path, child: subprocess.Popen[bytes]) -> str | None:
    deadline = time.monotonic() + START_ACK_TIMEOUT_SECONDS
    while True:
        if started.is_file():
            return None
        if child.poll() is not None:
            return "launch admission coordinator exited without acknowledging startup"
        if time.monotonic() >= deadline:
            return (
                "launch admission coordinator did not acknowledge startup "
                f"within {START_ACK_TIMEOUT_SECONDS:g}s"
            )
        time.sleep(_ACK_POLL_SECONDS)


def _coordinator_alive(root: Path) -> bool:
    pid = _sidecar_pid(root)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _sidecar_pid(root: Path) -> int:
    sidecar = root / "sidecar.json"
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    pid = payload.get("pid") if isinstance(payload, dict) else None
    return int(pid) if isinstance(pid, int) else 0


def _terminate(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=_PID_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=1.0)


if __name__ == "__main__":
    raise SystemExit(main())
