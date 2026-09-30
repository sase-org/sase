"""Join worker: ``sase tool _join RUN`` follows a detached run into a log."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_join, tool_run_show
from sase.feature_flags import override_flags
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import ToolRunCliRequest
from sase.tool.executor_recording import finish_tool_run
from sase.tool.handoff import reserve_handoff_run
from sase.tool.join_worker import _mapped_exit_code, execute_join_run, join_worker_argv


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


def _starter(name: str = "agent-1") -> dict[str, object]:
    return {
        "agent": name,
        "pid": os.getpid(),
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }


def _reserve_detached(
    *words: str, agent: str = "agent-1", owner_id: str = "proc-join-test"
) -> str:
    resolved = resolve_run_argv(list(words))
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id=owner_id,
        agent=agent,
        starter=_starter(agent),
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def _shown(run_id: str) -> dict:
    shown = tool_run_show(run_id)
    run = shown.get("run")
    assert isinstance(run, dict)
    return run


def _settle(
    run_id: str,
    *,
    state: str,
    exit_code: int | None,
    terminal_cause: str,
    owner_id: str = "proc-join-test",
) -> None:
    from sase.core.tool_run import tool_run_claim

    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": owner_id,
            "wrapper_pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        }
    )
    assert claimed.get("outcome") == "claimed", claimed
    assert finish_tool_run(
        run_id,
        state=state,
        exit_code=exit_code,
        duration_ms=12,
        terminal_cause=terminal_cause,
    )


def test_join_argv_uses_the_hidden_join_entrypoint() -> None:
    import sys

    assert join_worker_argv("abc123") == [
        sys.executable,
        "-m",
        "sase",
        "tool",
        "_join",
        "abc123",
    ]


def test_mapped_exit_code_covers_recorded_signal_stop_and_lost() -> None:
    assert _mapped_exit_code({"exit_code": 3}) == 3
    assert _mapped_exit_code({"exit_code": 0}) == 0
    assert _mapped_exit_code({"signal": 15}) == 143
    assert _mapped_exit_code({"signal": 9}) == 137
    assert _mapped_exit_code({"terminal_cause": "stop_requested"}) == 143
    assert _mapped_exit_code({"terminal_cause": "lost"}) == 1
    assert _mapped_exit_code({}) == 1


def test_join_requires_a_run_and_a_monitor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    assert execute_join_run("  ") == 2
    assert "Usage" in capsys.readouterr().err
    assert execute_join_run("abc123") == 2
    assert "no joining monitor" in capsys.readouterr().err


def test_join_refuses_an_unknown_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    assert execute_join_run("deadbeef" * 4) == 1
    assert "was not found" in capsys.readouterr().err


def test_join_refuses_a_run_joined_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve_detached("--", "true")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-elsewhere",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    assert execute_join_run(run_id) == 1
    err = capsys.readouterr().err
    assert "cannot be joined" in err
    assert f"sase tool show {run_id}" in err


def test_join_replay_settles_and_mirrors_the_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve_detached("--", "sh", "-c", "exit 3")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-1",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    _settle(run_id, state="failed", exit_code=3, terminal_cause="exited")
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    code = execute_join_run(run_id)
    captured = capsys.readouterr()
    assert code == 3
    assert "failed/3" in captured.err
    assert f"sase tool show {run_id} -l" in captured.err


def test_join_streams_pre_join_output_and_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    with override_flags(tool_run_escalation=True):
        monkeypatch.setenv("SASE_AGENT", "1")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(exist_ok=True)
        from sase.core.process_identity import process_identity_token

        runner_pid = os.getpid()
        (artifacts / "agent_meta.json").write_text(
            json.dumps(
                {
                    "pid": runner_pid,
                    "process_identity": process_identity_token(runner_pid),
                    "name": "agent-1",
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        from sase.tool.detach import execute_detached

        detach_code = execute_detached(
            ToolRunCliRequest(
                quiet=False,
                verbose=False,
                tail_lines=200,
                words=("--", "sh", "-c", "echo pre-join-output; exit 0"),
                hand_off=False,
                detach=True,
                tail_lines_explicit=False,
                keep_going=False,
                fail_fast=False,
            )
        )
        assert detach_code == 0
        out = capsys.readouterr().out
        run_id = next(
            line.split("sase tool run ")[1].strip().split()[0]
            for line in out.splitlines()
            if line.startswith("sase tool run ")
        )
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-1",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    from sase.tool.control_wait import wait_for_settlement

    envelope = wait_for_settlement(run_id, timeout_s=30.0)
    assert envelope is not None
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    worker_code = execute_join_run(run_id)
    captured = capsys.readouterr()
    assert worker_code == 0
    assert "pre-join-output" in captured.out
    assert "succeeded" in captured.err


def test_join_stop_requests_through_the_owner_and_exits_143(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.follow_run import FollowOutcome

    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve_detached("--", "sleep", "30")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-1",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-1")
    monkeypatch.setattr(
        "sase.tool.follow_run.follow_run",
        lambda run_id_, **_: FollowOutcome(kind="stopped", envelope=None),
    )
    waits: list[str] = []
    monkeypatch.setattr(
        "sase.tool.join_worker._wait_for_settlement",
        lambda run_id_: waits.append(run_id_),
    )
    code = execute_join_run(run_id)
    assert code == 143
    assert waits == [run_id]
    run = _shown(run_id)
    stop = run.get("stop_request")
    assert isinstance(stop, dict)
    assert stop.get("requested_by") == "sase"
    assert "mon-1" in str(stop.get("reason"))
    capsys.readouterr()


def test_join_stop_names_a_timeout_intent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool import join_worker

    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve_detached("--", "sleep", "30")
    monkeypatch.setattr(
        "sase.procs.runtime.read_termination_intent", lambda _proc: "total-timeout"
    )
    join_worker._request_owner_stop(run_id, "mon-9")
    run = _shown(run_id)
    stop = run.get("stop_request")
    assert isinstance(stop, dict)
    assert "mon-9" in str(stop.get("reason"))
    assert "total-timeout" in str(stop.get("reason"))
