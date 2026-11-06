"""Watchdog behavior for detached tool runs."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ._detach_helpers import clean_env, detach_request
from sase.core.tool_run import (
    tool_run_reserve_staged_join,
    tool_run_show,
)
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import execute_tool_run
from sase.tool.handoff import reserve_handoff_run


def _sleeper_agent_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> subprocess.Popen:
    """Agent env whose runner is a sacrificial sleeper the test can kill."""

    artifacts = tmp_path / f"artifacts-{name}"
    artifacts.mkdir(exist_ok=True)
    sleeper = subprocess.Popen(
        ["sleep", "300"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"pid": sleeper.pid, "name": name}), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return sleeper


def _settle_run_id(run_id: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    shown = tool_run_show(run_id)["run"]
    while time.monotonic() < deadline and (
        shown is None or shown.get("state") in ("created", "running")
    ):
        time.sleep(0.2)  # sase-test-wait: poll interval while the run settles
        shown = tool_run_show(run_id)["run"]
    return shown


def test_watchdog_stops_unjoined_run_when_starter_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    clean_env(monkeypatch, tmp_path)
    sleeper = _sleeper_agent_env(monkeypatch, tmp_path, "agent-1")
    try:
        code = execute_tool_run(detach_request("--", "sh", "-c", "sleep 30"))
        assert code == 0
        run_id = next(
            line.split("sase tool run ")[1].strip().split()[0]
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("sase tool run ")
        )
        sleeper.kill()
        sleeper.wait()
        shown = _settle_run_id(run_id)
        assert shown["state"] == "signaled"
        assert shown["terminal_cause"] == "stop_requested"
        stop = shown.get("stop_request")
        assert isinstance(stop, dict)
        assert stop.get("requested_by") == "sase"
        assert stop.get("reason") == "starter agent agent-1 ended without joining"
        for proc in read_procs(tag=f"tool-run:{run_id}"):
            wait_for_proc(proc.proc_id, timeout=30)
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def test_watchdog_reports_ended_join_monitor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.core.tool_run import tool_run_join
    from sase.procs import read_procs, wait_for_proc

    clean_env(monkeypatch, tmp_path)
    sleeper = _sleeper_agent_env(monkeypatch, tmp_path, "agent-1")
    try:
        code = execute_tool_run(detach_request("--", "sh", "-c", "sleep 30"))
        assert code == 0
        run_id = next(
            line.split("sase tool run ")[1].strip().split()[0]
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("sase tool run ")
        )
        joined = tool_run_join(
            {
                "schema_version": 1,
                "run_id": run_id,
                "joiner_kind": "monitor",
                "joiner_id": "mon-gone",
                "agent": "agent-1",
            }
        )
        assert joined.get("outcome") == "joined"
        sleeper.kill()
        sleeper.wait()
        shown = _settle_run_id(run_id)
        assert shown["state"] == "signaled"
        assert shown["terminal_cause"] == "stop_requested"
        stop = shown.get("stop_request")
        assert isinstance(stop, dict)
        assert stop.get("requested_by") == "sase"
        assert stop.get("reason") == "joining monitor mon-gone ended"
        for proc in read_procs(tag=f"tool-run:{run_id}"):
            wait_for_proc(proc.proc_id, timeout=30)
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def test_watchdog_preserves_run_joined_to_active_monitor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    import sase.tool.adopt as adopt_module

    from sase.core.tool_run import tool_run_join

    clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(adopt_module, "_WATCHDOG_POLL_SECONDS", 0.05)
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(
            status="running", origin="cli", proc_id=proc_id
        ),
    )
    dead_starter = {
        "agent": "agent-1",
        "pid": 2**30,
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }
    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id="proc-watch-live",
        agent="agent-1",
        starter=dead_starter,
    )
    assert reservation.reserved
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-live",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"

    real_sleep = time.sleep
    polls = {"count": 0}

    class _StopWatch(Exception):
        pass

    def _counting_sleep(seconds: float) -> None:
        polls["count"] += 1
        if polls["count"] >= 3:
            raise _StopWatch
        real_sleep(seconds)

    monkeypatch.setattr(adopt_module.time, "sleep", _counting_sleep)
    thread = threading.Thread(
        target=adopt_module._watch_starter,
        args=(reservation.run_id, dead_starter),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=10)
    assert polls["count"] >= 3
    shown = tool_run_show(reservation.run_id)["run"]
    assert shown.get("stop_request") is None
    assert shown["state"] in ("created", "running")


def test_watchdog_preserves_run_with_staged_join_reservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import threading

    import sase.tool.adopt as adopt_module

    clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(adopt_module, "_WATCHDOG_POLL_SECONDS", 0.05)
    dead_starter = {
        "agent": "agent-1",
        "pid": 2**30,
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-watch-staged",
        agent="agent-1",
        starter=dead_starter,
    )
    assert reservation.reserved
    staged = tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "staged_id": "staged-watch",
            "monitor_id": "mon-staged",
            "agent": "agent-1",
        }
    )
    assert staged.get("outcome") == "reserved"

    real_sleep = time.sleep
    polls = {"count": 0}

    class _StopWatch(Exception):
        pass

    def _counting_sleep(seconds: float) -> None:
        polls["count"] += 1
        if polls["count"] >= 3:
            raise _StopWatch
        real_sleep(seconds)

    monkeypatch.setattr(adopt_module.time, "sleep", _counting_sleep)
    thread = threading.Thread(
        target=adopt_module._watch_starter,
        args=(reservation.run_id, dead_starter),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=10)
    assert polls["count"] >= 3
    shown = tool_run_show(reservation.run_id)["run"]
    assert shown.get("stop_request") is None
    assert shown["state"] in ("created", "running")
    assert shown.get("staged_join_reservation", {}).get("staged_id") == "staged-watch"
