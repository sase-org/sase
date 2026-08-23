"""Shared helpers for :mod:`sase.monitor.supervise` tests.

Builds a monitor member's artifacts dir and project claim, then either
invokes :func:`sase.monitor.supervise.run_supervisor` in-process or drives
the supervisor as a child process (including the override-driver used to
inject timing constants).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.monitor.transaction import MONITOR_GO_MARKER
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file

# A hard liveness deadline for the supervisor child process: it must not
# still be alive this long after every node in scope arranges a 30s hold
# (sleep 30, or an infinite echo loop) for a descendant or pipe-EOF wait.
# Less than half the 30s hold so a reintroduced wait still fails
# deterministically, with headroom for host scheduling pressure. Do not
# raise it to quiet a failure -- a child still alive at this deadline is a
# real hang.
_NO_HANG_TIMEOUT = 15.0

_SUPERVISOR_DRIVER_SETUP_FAILURE = 91

_SUPERVISOR_OVERRIDE_DRIVER = f"""\
import json
import sys

try:
    import sase.monitor.supervise as supervise

    for name, value in json.loads(sys.argv[2]).items():
        getattr(supervise, name)  # a renamed constant must not be skipped
        setattr(supervise, name, value)
except BaseException as exc:  # noqa: BLE001 - reported through the exit code
    print(f"supervisor driver setup failed: {{exc!r}}", file=sys.stderr)
    raise SystemExit({_SUPERVISOR_DRIVER_SETUP_FAILURE}) from None

raise SystemExit(supervise.run_supervisor(sys.argv[1]))
"""


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


@pytest.fixture(autouse=True)
def _restore_signal_handlers() -> Iterator[None]:
    """``run_supervisor`` installs process-wide SIGTERM/SIGINT handlers.

    Called directly (not via a subprocess) it would otherwise leak that
    installation into the rest of the test session.
    """
    original_term = signal.getsignal(signal.SIGTERM)
    original_int = signal.getsignal(signal.SIGINT)
    original_hup = signal.getsignal(signal.SIGHUP)
    yield
    signal.signal(signal.SIGTERM, original_term)
    signal.signal(signal.SIGINT, original_int)
    signal.signal(signal.SIGHUP, original_hup)


def _make_member(
    tmp_path: Path,
    *,
    command: str,
    timeout_seconds: float = 60.0,
    idle_timeout_seconds: float = 0.0,
    next_action: str | None = None,
    workspace_num: int = 1,
    claim_workflow: str = "ace-monitor",
    go_barrier: bool = True,
) -> tuple[str, str]:
    extra_meta = {}
    if idle_timeout_seconds > 0:
        extra_meta["monitor_idle_timeout_seconds"] = idle_timeout_seconds
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(workspace_num, claim_workflow, "acme", pid=os.getpid())
        ],
    )
    artifacts_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="abc123def456",
        monitor_command=command,
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=timeout_seconds,
        monitor_next_action=next_action,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=workspace_num,
        **extra_meta,
    )
    if go_barrier:
        (Path(artifacts_dir) / MONITOR_GO_MARKER).write_text("{}", encoding="utf-8")
    return artifacts_dir, project_file


def _run_supervisor_subprocess(
    artifacts_dir: str,
    *,
    overrides: Mapping[str, float] | None = None,
    liveness_timeout: float = _NO_HANG_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    if overrides is None:
        argv = [
            sys.executable,
            "-m",
            "sase.monitor.supervise",
            "--artifacts-dir",
            artifacts_dir,
        ]
    else:
        argv = [
            sys.executable,
            "-c",
            _SUPERVISOR_OVERRIDE_DRIVER,
            artifacts_dir,
            json.dumps(overrides),
        ]
    try:
        completed = subprocess.run(
            argv,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=liveness_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"supervisor subprocess did not exit within {liveness_timeout:g}s; "
            f"stdout={exc.stdout!r}; stderr={exc.stderr!r}"
        )
    if completed.returncode == _SUPERVISOR_DRIVER_SETUP_FAILURE:
        pytest.fail(f"supervisor driver setup failed: {completed.stderr}")
    return completed


def _terminate_pid(pid: int) -> None:
    if not is_process_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    while is_process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)  # sase-test-wait: poll orphaned grandchild cleanup
    if is_process_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
