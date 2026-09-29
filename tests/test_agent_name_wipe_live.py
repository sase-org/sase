"""Live-process wipe tests: termination, stop verification, real exits.

Split from ``tests.test_agent_name_wipe``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.names import rebuild_name_registry, wipe_agent_name_for_reuse
from sase.core.process_identity import process_identity_token

from tests._agent_name_wipe_helpers import make_wipe_artifact

__all__ = [
    "test_wipe_live_agent_keeps_artifact_when_stop_is_unverified",
    "test_wipe_live_agent_terminates_and_releases_workspace",
    "test_wipe_live_agent_waits_for_real_process_exit_before_removal",
]


def _start_agent_process(
    tmp_path: Path,
    *,
    mode: str,
) -> subprocess.Popen[str]:
    ready_path = tmp_path / f"{mode}.ready"
    script = """
import signal
import sys
import time
from pathlib import Path

ready_path = Path(sys.argv[1])
mode = sys.argv[2]

def handle_term(signum, frame):
    if mode == "delay":
        time.sleep(0.2)
        raise SystemExit(0)

if mode == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, handle_term)

ready_path.write_text("ready", encoding="utf-8")
while True:
    time.sleep(0.05)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(ready_path), mode],
        text=True,
        preexec_fn=os.setsid,
    )
    deadline = time.monotonic() + 5.0
    while not ready_path.exists() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"agent process exited early: {process.returncode}")
        time.sleep(0.01)  # sase-test-wait: child process writes readiness file
    if not ready_path.exists():
        raise AssertionError("agent process did not signal readiness")
    return process


def _cleanup_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=5)


def test_wipe_live_agent_terminates_and_releases_workspace(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_wipe_artifact(
        tmp_path, "20260508120000", "foo", meta={"pid": 1234}
    )
    kill_result = SimpleNamespace(status="killed", error=None)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch(
                "sase.agent.names._wipe_execute.is_process_alive",
                side_effect=[True, False, False],
            ),
            patch(
                "sase.agent.names._wipe_execute.request_user_kill",
                return_value=kill_result,
            ) as request_kill,
            patch(
                "sase.agent.names._wipe_execute._release_artifact_workspace"
            ) as release,
        ):
            result = wipe_agent_name_for_reuse("foo")

    request_kill.assert_called_once()
    assert request_kill.call_args.kwargs["wait"] is False
    release.assert_called_once_with(artifacts_dir)
    assert result.killed_processes == 1
    assert not artifacts_dir.exists()


def test_wipe_live_agent_keeps_artifact_when_stop_is_unverified(
    tmp_path: Path,
) -> None:
    artifacts_dir = make_wipe_artifact(
        tmp_path, "20260508120000", "foo", meta={"pid": 1234}
    )
    kill_result = SimpleNamespace(status="killed", error=None)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch("sase.agent.names._wipe_execute.is_process_alive", return_value=True),
            patch(
                "sase.agent.names._wipe_execute.request_user_kill",
                return_value=kill_result,
            ),
            patch("sase.agent.names._wipe_execute._FORCE_REUSE_STOP_GRACE_SECONDS", 0),
            patch(
                "sase.agent.names._wipe_execute._FORCE_REUSE_SIGKILL_CONFIRM_SECONDS",
                0,
            ),
            patch("sase.agent.names._wipe_execute.time.sleep", return_value=None),
            patch(
                "sase.agent.names._wipe_execute._release_artifact_workspace"
            ) as release,
        ):
            result = wipe_agent_name_for_reuse("foo")

    assert result.artifact_dirs_removed == ()
    assert result.errors
    assert "still live after stop attempt" in result.errors[0]
    assert artifacts_dir.exists()
    release.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    [
        pytest.param("delay", "killed", id="graceful"),
        pytest.param("ignore", "force_killed", id="escalated"),
    ],
)
def test_wipe_live_agent_waits_for_real_process_exit_before_removal(
    tmp_path: Path,
    mode: str,
    expected_status: str,
) -> None:
    process = _start_agent_process(tmp_path, mode=mode)
    artifacts_dir = make_wipe_artifact(
        tmp_path,
        f"20260508120000-{mode}",
        f"foo-{mode}",
        meta={
            "pid": process.pid,
            "process_identity": process_identity_token(process.pid),
        },
    )

    try:
        with patch.object(Path, "home", return_value=tmp_path):
            rebuild_name_registry()
            result = wipe_agent_name_for_reuse(f"foo-{mode}")

        process.wait(timeout=5)
    finally:
        _cleanup_process_group(process)

    assert result.errors == ()
    assert result.killed_processes == 1
    assert str(artifacts_dir.resolve()) in result.artifact_dirs_removed
    assert not artifacts_dir.exists()
    marker = artifacts_dir / ".sase_user_kill_pending"
    assert not marker.exists()
    assert process.returncode is not None
    if expected_status == "force_killed":
        assert process.returncode < 0
