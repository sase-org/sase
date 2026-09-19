from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from sase.core.tool_run import tool_run_list


SASE = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "sase"


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    env.pop("SASE_AGENT_NAME", None)
    env.pop("SASE_MONITOR_ID", None)
    env.pop("SASE_PROC_ID", None)
    env.pop("SASE_TOOL_RUN_ID", None)
    return env


def _wait_running(env: dict[str, str], timeout: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            listed = tool_run_list({"schema_version": 1, "limit": 10})
        except Exception:  # noqa: BLE001 - store may still be creating.
            time.sleep(0.05)  # sase-test-wait: store create race
            continue
        for run in listed.get("runs") or ():
            if run.get("state") == "running":
                return run
        time.sleep(0.05)  # sase-test-wait: poll running ToolRun row
    raise AssertionError("tool run did not become running")


@pytest.mark.skipif(not SASE.exists(), reason="workspace sase executable missing")
def test_sigterm_is_signaled_143(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    env = _env(home)
    proc = subprocess.Popen(
        [str(SASE), "tool", "run", "--", "sleep", "30"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_running(env)
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=8)
        assert code == 143
        listed = tool_run_list({"schema_version": 1, "limit": 10})
        run = listed["runs"][0]
        assert run["state"] == "signaled"
        assert run["exit_code"] == 143
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.skipif(not SASE.exists(), reason="workspace sase executable missing")
def test_sigint_is_interrupted_130(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    env = _env(home)
    proc = subprocess.Popen(
        [str(SASE), "tool", "run", "--", "sleep", "30"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_running(env)
        proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=8)
        assert code == 130
        listed = tool_run_list({"schema_version": 1, "limit": 10})
        run = listed["runs"][0]
        assert run["state"] == "interrupted"
        assert run["exit_code"] == 130
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.skipif(not SASE.exists(), reason="workspace sase executable missing")
def test_sigkill_wrapper_marks_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    env = _env(home)
    child_pid_file = tmp_path / "child.pid"
    script = tmp_path / "hold.py"
    script.write_text(
        "import os, time\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    proc = subprocess.Popen(
        [str(SASE), "tool", "run", "--", sys.executable, str(script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid: int | None = None
    try:
        run = _wait_running(env)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not child_pid_file.exists():
            time.sleep(0.05)  # sase-test-wait: child pid file
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        # CLI list reconciles; call the handler path via another sase tool runs.
        runs_proc = subprocess.run(
            [str(SASE), "tool", "runs", "-j"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert runs_proc.returncode == 0
        import json

        payload = json.loads(runs_proc.stdout)
        lost = next(item for item in payload["runs"] if item["run_id"] == run["run_id"])
        assert lost["state"] == "lost"
        assert lost["lost_reason"] == "runner exited without settling"
        assert lost.get("duration_ms") is None
        assert lost.get("exit_code") is None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except OSError:
                pass
