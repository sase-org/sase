"""Ceiling-bounded ``sase tool wait`` and ``sase tool show -F``."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_claim, tool_run_finish
from sase.tool.argv import resolve_run_argv
from sase.tool.control import ToolWaitCliRequest, handle_wait
from sase.tool.handoff import reserve_handoff_run
from sase.tool.liveness import current_boot_id
from sase.tool.query import ToolShowCliRequest, handle_show
from sase.tool.routing import (
    escalation_block,
    is_joinable,
    sync_wait_budget,
)


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
        "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _agent(monkeypatch: pytest.MonkeyPatch, name: str = "agent-1") -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)


def _starter(name: str = "agent-1") -> dict:
    pid = os.getpid()
    return {
        "agent": name,
        "pid": pid,
        "boot_id": current_boot_id() or None,
        "process_start_identity": process_identity_token(pid) or None,
    }


def _begin_detached_running(name: str = "agent-1") -> str:
    """Reserve and claim a starter-scoped handoff run that stays running."""

    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id="proc-bounded-1",
        agent=name,
        starter=_starter(name),
    )
    assert reservation.reserved, reservation.error
    pid = os.getpid()
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "owner_kind": "proc",
            "owner_id": "proc-bounded-1",
            "wrapper_pid": pid,
            "boot_id": current_boot_id() or None,
            "process_start_identity": process_identity_token(pid) or None,
        }
    )
    assert claimed["outcome"] == "claimed"
    return reservation.run_id


def _begin_foreground_running() -> str:
    pid = os.getpid()
    return tool_run_begin(
        {
            "schema_version": 1,
            "definition": {
                "schema_version": 1,
                "name": "seeded",
                "argv": ["true"],
                "description": "",
                "stages": "none",
                "inputs": [],
                "env": [],
                "args": "allow",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "wrapper_pid": pid,
            "boot_id": current_boot_id() or None,
            "process_start_identity": process_identity_token(pid) or None,
        }
    )["run"]["run_id"]


def _finish(run_id: str) -> None:
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "succeeded",
            "duration_ms": 5,
            "exit_code": 0,
        }
    )


def test_sync_wait_budget_needs_agent_and_ceilings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    assert sync_wait_budget() is None  # no agent
    _agent(monkeypatch)
    monkeypatch.delenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", raising=False)
    monkeypatch.delenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", raising=False)
    assert sync_wait_budget() is None  # ceilings unset
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    assert sync_wait_budget() == {
        "budget_seconds": 510,
        "source": "hard",
        "ceiling_seconds": 600,
        "margin_seconds": 90,
    }


def test_sync_wait_budget_soft_and_tie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "1200")
    assert sync_wait_budget() == {
        "budget_seconds": 1200,
        "source": "soft",
        "soft_ceiling_seconds": 1200,
    }
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    soft_wins = sync_wait_budget()
    assert soft_wins is not None
    assert soft_wins["budget_seconds"] == 510
    assert soft_wins["source"] == "hard"
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "100")
    soft = sync_wait_budget()
    assert soft is not None
    assert soft["budget_seconds"] == 100
    assert soft["source"] == "soft"


def test_wait_budget_without_timeout_exits_124_with_join_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_detached_running()
    started = time.monotonic()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id))
    elapsed = time.monotonic() - started
    assert code == 124
    assert elapsed < 20  # the 1s budget bounds the wait, not the default
    err = capsys.readouterr().err
    assert "is still running" in err
    assert "was not stopped" in err
    assert "SASE_PROVIDER_SYNC_CEILING_SECONDS=2" in err
    assert f"sase monitor start -J {run_id}" in err
    assert f"sase tool wait {run_id}" in err
    assert "stopped when this agent's turn ends" in err


def test_wait_clamps_explicit_timeout_to_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_detached_running()
    started = time.monotonic()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id, timeout_raw="90s"))
    elapsed = time.monotonic() - started
    assert code == 124
    assert elapsed < 20  # clamped to the 1s budget, not 90s
    err = capsys.readouterr().err
    assert "clamped" in err
    assert "is still running" in err


def test_wait_soft_budget_wording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS", "1")
    run_id = _begin_detached_running()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id))
    assert code == 124
    err = capsys.readouterr().err
    assert "soft ceiling" in err
    assert "SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS=1" in err


def test_wait_non_joinable_prints_no_join_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch, name="agent-1")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_detached_running(name="agent-2")  # another agent's run
    code = handle_wait(ToolWaitCliRequest(run_id=run_id))
    assert code == 124
    err = capsys.readouterr().err
    assert "is still running" in err
    assert "monitor start -J" not in err
    assert f"sase tool wait {run_id}" in err


def test_wait_json_escalation_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_detached_running()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id, json=True))
    assert code == 124
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["timed_out"] is True
    escalation = payload["escalation"]
    assert escalation["budget_seconds"] == 1
    assert escalation["source"] == "hard"
    assert escalation["joinable"] is True
    assert f"sase monitor start -J {run_id}" in escalation["join_command"]
    assert "is still running" in captured.err


def test_wait_human_never_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_foreground_running()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id, timeout_raw="1"))
    assert code == 124
    err = capsys.readouterr().err
    assert err.strip() == f"tool run {run_id} is still running"


def test_show_follow_budget_exits_124_with_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _agent(monkeypatch)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "2")
    run_id = _begin_detached_running()
    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=False, logs=False, follow=True)
    )
    assert code == 124
    err = capsys.readouterr().err
    assert "is still running" in err
    assert "was not stopped" in err
    assert f"sase monitor start -J {run_id}" in err


def test_show_follow_without_budget_parity_on_settled_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground_running()
    _finish(run_id)
    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=False, logs=False, follow=True)
    )
    assert code == 0
    assert run_id in capsys.readouterr().out


def test_is_joinable_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clean_env(monkeypatch, tmp_path)
    live = _starter("agent-1")
    assert (
        is_joinable(
            {"state": "running", "starter": live},
            env={"SASE_AGENT_NAME": "agent-1"},
        )
        is True
    )
    assert (
        is_joinable(
            {"state": "succeeded", "starter": live},
            env={"SASE_AGENT_NAME": "agent-1"},
        )
        is False
    )
    assert (
        is_joinable({"state": "running"}, env={"SASE_AGENT_NAME": "agent-1"}) is False
    )
    assert (
        is_joinable(
            {
                "state": "running",
                "starter": live,
                "stop_request": {"requested_by": "sase"},
            },
            env={"SASE_AGENT_NAME": "agent-1"},
        )
        is False
    )
    assert (
        is_joinable(
            {"state": "running", "starter": live},
            env={"SASE_AGENT_NAME": "agent-2"},
        )
        is False
    )
    joined_elsewhere = {
        "state": "running",
        "starter": live,
        "join": {"kind": "monitor", "id": "mon-other"},
    }
    assert is_joinable(joined_elsewhere, env={"SASE_AGENT_NAME": "agent-1"}) is False
    assert (
        is_joinable(
            joined_elsewhere,
            env={"SASE_AGENT_NAME": "agent-1", "SASE_MONITOR_ID": "mon-other"},
        )
        is True
    )
    block = escalation_block(
        {"state": "running", "starter": live, "run_id": "abc", "tool_name": "check"},
        {"budget_seconds": 510, "source": "hard", "ceiling_seconds": 600},
        "abc",
        env={"SASE_AGENT_NAME": "agent-1"},
    )
    assert "monitor start -J abc" in block
    assert "SASE_PROVIDER_SYNC_CEILING_SECONDS=600" in block
