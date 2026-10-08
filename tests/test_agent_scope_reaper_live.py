"""Live systemd reaper regression for orphaned ``sase-agent`` scopes."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.agent.scope_sweep import (
    discover_agent_scopes,
    _read_scope_members,
    reap_orphaned_agent_scopes,
)
from sase.detach_scope import (
    DETACH_SCOPE_DISABLE_ENV,
    _cgroup_has_user_manager,
    _user_manager_reachable,
)


def _cgroup_v2() -> bool:
    try:
        text = Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        len(line.split(":", 2)) == 3
        and line.split(":", 2)[0] == "0"
        and line.split(":", 2)[1] == ""
        for line in text.splitlines()
    )


def _pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def test_live_reaper_sweeps_orphaned_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux":
        pytest.skip("Linux-only cgroup regression")
    monkeypatch.delenv(DETACH_SCOPE_DISABLE_ENV, raising=False)
    monkeypatch.delenv("SASE_AXE_DISABLE_SYSTEMD_SCOPE", raising=False)
    if not _cgroup_v2():
        pytest.skip("cgroup v2 is unavailable")
    if not (_cgroup_has_user_manager() or _user_manager_reachable()):
        pytest.skip("user systemd manager is unreachable")
    if shutil.which("systemd-run") is None:
        pytest.skip("systemd-run is unavailable")

    unit = f"sase-agent-{os.getpid()}-{time.time_ns()}.scope"
    started = subprocess.run(
        [
            "systemd-run",
            "--user",
            "--scope",
            "--collect",
            f"--unit={unit}",
            "--",
            "sh",
            "-c",
            "(while :; do sleep 0.2; done) </dev/null >/dev/null 2>&1 & exit 0",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if started.returncode != 0:
        pytest.skip(f"systemd-run failed: {started.stderr.strip()[-500:]}")

    loop_pids: list[int] = []
    try:
        # The launcher shell exits at once, leaving only the background loop.
        time.sleep(1.0)  # sase-test-wait: allow scope to settle
        preview = reap_orphaned_agent_scopes(
            apply=False, min_age_seconds=0, only_units={unit}
        )
        assert preview.scanned == 1, f"expected one scope, got {preview}"
        assert len(preview.reaped) == 1
        assert preview.reaped[0].unit == unit
        for scope in discover_agent_scopes(only_units={unit}):
            loop_pids.extend(member.pid for member in _read_scope_members(scope.path))
        assert loop_pids, "expected the background loop to hold the scope"

        result = reap_orphaned_agent_scopes(
            apply=True, min_age_seconds=0, only_units={unit}
        )
        assert len(result.reaped) == 1
        assert result.errors == 0

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if all(_pid_gone(pid) for pid in loop_pids):
                break
            time.sleep(0.2)  # sase-test-wait: poll until reaped loop pids exit
        assert all(_pid_gone(pid) for pid in loop_pids), (
            f"loop pids survived the reap: {loop_pids}"
        )

        deadline = time.monotonic() + 10.0
        scope_gone = False
        while time.monotonic() < deadline:
            check = reap_orphaned_agent_scopes(
                apply=False, min_age_seconds=0, only_units={unit}
            )
            if check.scanned == 0 or check.empty == 1:
                scope_gone = True
                break
            time.sleep(0.5)  # sase-test-wait: poll until systemd collects emptied scope
        assert scope_gone, "orphaned scope was not collected after the reap"
    finally:
        for pid in loop_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
