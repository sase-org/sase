"""Starter liveness and detached-run cleanup behavior."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from ._detach_helpers import agent_env, clean_env
from sase.core.tool_run import tool_run_reserve_staged_join, tool_run_show
from sase.tool.argv import resolve_run_argv
from sase.tool.detach_cleanup import stop_unjoined_detached_runs
from sase.tool.handoff import reserve_handoff_run
from sase.tool.starter import resolve_starter, starter_alive


def test_resolve_starter_reads_runner_meta_and_alive_needs_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    assert resolve_starter().reason == "not-agent"
    agent_env(monkeypatch, tmp_path, name="agent-9")
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


def test_starter_alive_sees_through_unreaped_zombies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.core.process_identity import process_identity_token

    clean_env(monkeypatch, tmp_path)
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
    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path, name="agent-1")
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


def test_cleanup_preserves_run_with_staged_join_reservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    agent_env(monkeypatch, tmp_path, name="agent-1")
    resolution = resolve_starter()
    assert resolution.resolved and resolution.starter is not None
    reserved = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-staged-reserved",
        agent="agent-1",
        starter=dict(resolution.starter),
    )
    assert reserved.reserved
    staged = tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": reserved.run_id,
            "staged_id": "staged-cleanup",
            "monitor_id": "mon-cleanup",
            "agent": "agent-1",
        }
    )
    assert staged.get("outcome") == "reserved"

    assert stop_unjoined_detached_runs() == 0
    shown = tool_run_show(reserved.run_id)["run"]
    assert shown.get("stop_request") is None
    assert shown.get("staged_join_reservation", {}).get("staged_id") == "staged-cleanup"


def test_cleanup_never_raises_without_agent_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    assert stop_unjoined_detached_runs() == 0
