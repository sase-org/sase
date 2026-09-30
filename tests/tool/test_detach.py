"""Starter-scoped detached runs: ``sase tool run -d/--detach``."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_claim, tool_run_list, tool_run_show
from sase.feature_flags import override_flags
from sase.tool.argv import resolve_run_argv
from sase.tool.detach_cleanup import stop_unjoined_detached_runs
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.handoff import reserve_handoff_run
from sase.tool.starter import resolve_starter, starter_alive


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _detach_request(
    *words: str,
    quiet: bool = False,
    verbose: bool = False,
    tail_lines_explicit: bool = False,
    keep_going: bool = False,
    fail_fast: bool = False,
    hand_off: bool = False,
) -> ToolRunCliRequest:
    return ToolRunCliRequest(
        quiet=quiet,
        verbose=verbose,
        tail_lines=200,
        words=tuple(words),
        hand_off=hand_off,
        detach=True,
        tail_lines_explicit=tail_lines_explicit,
        keep_going=keep_going,
        fail_fast=fail_fast,
    )


def _agent_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    name: str = "agent-1",
    pid: int | None = None,
) -> Path:
    """Agent env whose runner PID is live (defaults to this test process)."""

    from sase.core.process_identity import process_identity_token

    runner_pid = pid if pid is not None else os.getpid()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": runner_pid,
                "process_identity": process_identity_token(runner_pid),
                "name": name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts


def _rows() -> list:
    listed = tool_run_list({"schema_version": 1, "limit": 100})
    return list(listed.get("runs") or [])


def test_detach_flag_off_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=False):
        code = execute_tool_run(_detach_request("--", "printf", "hi"))
    assert code == 2
    assert "not enabled" in capsys.readouterr().err
    assert _rows() == []


def test_detach_refuses_human_with_handoff_alternative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("--", "printf", "hi"))
    assert code == 2
    captured = capsys.readouterr()
    assert "sase tool run -H" in captured.err
    assert _rows() == []


def test_detach_refuses_hand_off_together_verbose_and_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=True):
        assert (
            execute_tool_run(_detach_request("--", "printf", "hi", hand_off=True)) == 2
        )
        capsys.readouterr()
        assert (
            execute_tool_run(_detach_request("--", "printf", "hi", verbose=True)) == 2
        )
        assert "verbose" in capsys.readouterr().err
        assert (
            execute_tool_run(
                _detach_request("--", "printf", "hi", tail_lines_explicit=True)
            )
            == 2
        )
        assert "tail-lines" in capsys.readouterr().err
    assert _rows() == []


def test_detach_refuses_inside_live_owner_and_parent_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-live")
    monkeypatch.setattr(
        "sase.procs.store.get_proc",
        lambda proc_id: SimpleNamespace(
            status="running", origin="cli", proc_id=proc_id
        ),
    )
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("--", "printf", "hi"))
    assert code == 2
    assert "proc-live" in capsys.readouterr().err
    monkeypatch.delenv("SASE_PROC_ID")

    resolved = resolve_run_argv(["--", "printf", "hi"])
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id="proc-1")
    assert reservation.reserved
    monkeypatch.setenv("SASE_TOOL_RUN_ID", reservation.run_id)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("--", "printf", "hi"))
    assert code == 2
    assert "parent tool run" in capsys.readouterr().err


def test_detach_unresolvable_starter_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("--", "printf", "hi"))
    assert code == 1
    captured = capsys.readouterr()
    assert (
        "cannot identify the starting agent runner; nothing was started" in captured.err
    )
    assert _rows() == []


def test_detach_accepts_long_tool_skipping_inline_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    (tmp_path / "sase").mkdir(exist_ok=True)
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "slow": {
                        "argv": ["sh", "-c", "exit 0"],
                        "args": "deny",
                        "duration_class": "long",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("slow"))
    assert code == 0
    captured = capsys.readouterr()
    run_id = next(
        line.split("sase tool run ")[1].strip().split()[0]
        for line in captured.out.splitlines()
        if line.startswith("sase tool run ")
    )
    assert "detached: stopped when this agent's turn ends" in captured.out
    assert f"sase monitor start -J {run_id}" in captured.out
    shown = tool_run_show(run_id)["run"]
    assert shown["starter"]["agent"] == "agent-1"
    assert shown["starter"]["pid"] == os.getpid()
    assert shown.get("join") is None
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    assert "tool-run-detached" in (tagged[0].tags or [])
    wait_for_proc(tagged[0].proc_id, timeout=30)


def test_detach_quiet_prints_only_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import wait_for_proc, read_procs

    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=True):
        code = execute_tool_run(_detach_request("--", "printf", "hi", quiet=True))
    assert code == 0
    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 1
    run_id = captured.out.strip()
    tagged = read_procs(tag=f"tool-run:{run_id}")
    assert len(tagged) == 1
    wait_for_proc(tagged[0].proc_id, timeout=30)


def test_detach_keep_going_travels_in_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    resolved = resolve_run_argv(["--", "printf", "hi"])
    starter = {
        "agent": "agent-1",
        "pid": os.getpid(),
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id="proc-9",
        agent="agent-1",
        starter=starter,
        continuation_mode="always",
    )
    assert reservation.reserved
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "owner_kind": "proc",
            "owner_id": "proc-9",
            "wrapper_pid": os.getpid(),
        }
    )
    assert claimed.get("outcome") == "claimed"
    launch = claimed.get("launch")
    assert isinstance(launch, dict)
    assert launch.get("continuation_mode") == "always"
    shown = tool_run_show(reservation.run_id)["run"]
    assert shown["starter"]["agent"] == "agent-1"


def test_resolve_starter_reads_runner_meta_and_alive_needs_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    assert resolve_starter().reason == "not-agent"
    _agent_env(monkeypatch, tmp_path, name="agent-9")
    resolution = resolve_starter()
    assert resolution.resolved
    assert resolution.starter is not None
    assert resolution.starter["agent"] == "agent-9"
    assert resolution.starter["pid"] == os.getpid()
    assert starter_alive(resolution.starter) is True
    assert (
        starter_alive(
            {
                "agent": "agent-9",
                "pid": 2**30,
                "boot_id": "boot-1",
                "process_start_identity": "boot-1:1",
            }
        )
        is False
    )


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
    while shown.get("state") in ("created", "running") and time.monotonic() < deadline:
        time.sleep(0.2)  # sase-test-wait: poll interval while the run settles
        shown = tool_run_show(run_id)["run"]
    return shown


def test_watchdog_stops_unjoined_run_when_starter_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.procs import read_procs, wait_for_proc

    _clean_env(monkeypatch, tmp_path)
    sleeper = _sleeper_agent_env(monkeypatch, tmp_path, "agent-1")
    try:
        with override_flags(tool_run_escalation=True):
            code = execute_tool_run(_detach_request("--", "sh", "-c", "sleep 30"))
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

    _clean_env(monkeypatch, tmp_path)
    sleeper = _sleeper_agent_env(monkeypatch, tmp_path, "agent-1")
    try:
        with override_flags(tool_run_escalation=True):
            code = execute_tool_run(_detach_request("--", "sh", "-c", "sleep 30"))
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

    _clean_env(monkeypatch, tmp_path)
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


def test_starter_alive_sees_through_unreaped_zombies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.core.process_identity import process_identity_token

    _clean_env(monkeypatch, tmp_path)
    sleeper = subprocess.Popen(
        ["sleep", "300"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        identity = process_identity_token(sleeper.pid)
        assert identity
        boot, _, _ = identity.partition(":")
        starter = {
            "agent": "agent-1",
            "pid": sleeper.pid,
            "boot_id": boot,
            "process_start_identity": identity,
        }
        assert starter_alive(starter) is True
        # Killed but never reaped: a zombie keeps its /proc entry and its
        # start identity, yet the runner has ended.
        sleeper.kill()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{sleeper.pid}/stat").read_text(encoding="utf-8")
            except OSError:
                break
            state = stat[stat.rfind(")") + 1 :].split()[0]
            if state == "Z":
                break
            time.sleep(0.05)  # sase-test-wait: SIGKILL lands asynchronously
        assert starter_alive(starter) is False
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass
        sleeper.wait()


def test_cleanup_stops_only_matching_unjoined_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent_env(monkeypatch, tmp_path, name="agent-1")
    resolution = resolve_starter()
    assert resolution.resolved and resolution.starter is not None

    mine = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-mine",
        agent="agent-1",
        starter=dict(resolution.starter),
    )
    assert mine.reserved
    foreign = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-foreign",
        agent="agent-2",
        starter={
            "agent": "agent-2",
            "pid": 2**30,
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert foreign.reserved
    plain = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-plain",
        agent="agent-1",
    )
    assert plain.reserved

    stopped = stop_unjoined_detached_runs()
    assert stopped == 1
    mine_shown = tool_run_show(mine.run_id)["run"]
    stop = mine_shown.get("stop_request")
    assert isinstance(stop, dict)
    assert stop.get("requested_by") == "sase"
    assert stop.get("reason") == "starter agent agent-1 ended without joining"
    assert tool_run_show(foreign.run_id)["run"].get("stop_request") is None
    assert tool_run_show(plain.run_id)["run"].get("stop_request") is None


def test_cleanup_never_raises_without_agent_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    assert stop_unjoined_detached_runs() == 0


def test_detached_runs_raise_no_settlement_notification() -> None:
    from sase.tool.notify import deliver_handoff_settlement

    run = {
        "run_id": "abc",
        "state": "succeeded",
        "launch_mode": "handoff",
        "owner_kind": "proc",
        "starter": {"agent": "agent-1", "pid": 1},
    }
    assert deliver_handoff_settlement(run) == "skipped"


def test_show_renders_starter_and_join(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool._query_shared import print_show

    _clean_env(monkeypatch, tmp_path)
    print_show(
        {
            "run": {
                "run_id": "abc",
                "launch_mode": "handoff",
                "starter": {"agent": "agent-1", "pid": 1},
                "join": {"kind": "monitor", "id": "mon-1", "joined_ts": 1720000000},
            }
        }
    )
    out = capsys.readouterr().out
    assert "detached by agent agent-1" in out
    assert "joined by monitor mon-1 at " in out
    capsys.readouterr()
    print_show({"run": {"run_id": "abc", "launch_mode": "handoff"}})
    out = capsys.readouterr().out
    assert "DETACHED" not in out
    assert "JOINED" not in out


def test_parser_detach_mutually_exclusive_with_hand_off() -> None:
    import argparse

    from sase.main.parser_tool import register_tool_parser

    parser = argparse.ArgumentParser(prog="sase")
    subs = parser.add_subparsers(dest="command")
    register_tool_parser(subs)
    args = parser.parse_args(["tool", "run", "-d", "--", "printf", "hi"])
    assert args.detach is True
    assert args.hand_off is False
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["tool", "run", "-H", "-d", "--", "printf", "hi"])
    assert excinfo.value.code == 2


def test_detached_owner_tags_carry_detached_marker() -> None:
    from sase.tool.handoff import owner_tags

    assert owner_tags("abc") == ["tool-run", "tool-run:abc"]
    assert owner_tags("abc", detached=True) == [
        "tool-run",
        "tool-run:abc",
        "tool-run-detached",
    ]
