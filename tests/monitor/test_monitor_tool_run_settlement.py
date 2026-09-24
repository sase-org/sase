"""Monitor settlement reconciles a monitor-owned hand-off ToolRun."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.core.tool_run import tool_run_claim, tool_run_show
from sase.monitor.proc_adapter import settle_monitor_followup
from sase.notifications.store import load_notifications
from sase.tool.argv import resolve_run_argv
from sase.tool.handoff import reserve_handoff_run
from sase.tool.liveness import current_boot_id

from ._fixtures import make_starter_agent, write_project_file

MONITOR_ID = "abc123def456"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _monitor_owned_running_run() -> str:
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]), owner_kind="monitor", owner_id=MONITOR_ID
    )
    assert reservation.reserved, reservation.error
    finished = subprocess.Popen(["true"])
    finished.wait()
    boot = current_boot_id()
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": reservation.run_id,
            "owner_kind": "monitor",
            "owner_id": MONITOR_ID,
            "wrapper_pid": finished.pid,
            "boot_id": boot,
            "process_start_identity": f"{boot}:1",
        }
    )
    assert claimed["outcome"] == "claimed"
    return reservation.run_id


def _make_monitor(tmp_path: Path, run_id: str, **extra: object) -> str:
    write_project_file("proj")
    return make_starter_agent(
        "proj",
        "20260906120000",
        "acme--mon",
        agent_session="acme",
        agent_session_role="monitor",
        monitor_id=MONITOR_ID,
        monitor_command="true",
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_stop_status="MONITORED",
        monitor_tool_run_id=run_id,
        monitor_state="completed",
        monitor_exit_code=3,
        cl_name="acme",
        workspace_dir=str(tmp_path),
        shell_kind="proc",
        **extra,
    )


def _state(artifacts_dir: str) -> dict[str, object]:
    return {
        "artifacts_dir": artifacts_dir,
        "proc_id": MONITOR_ID,
        "monitor_state": "failed",
        "monitor_exit_code": 3,
        "monitor_elapsed_seconds": 0.0,
        "exit_code": 3,
        "termination_reason": "error",
        "status": "error",
    }


def _run(run_id: str) -> dict[str, object]:
    run = tool_run_show(run_id)["run"]
    assert isinstance(run, dict)
    return run


def test_monitor_settlement_reconciles_its_tool_run_without_notifying(
    tmp_path: Path,
) -> None:
    run_id = _monitor_owned_running_run()
    artifacts_dir = _make_monitor(tmp_path, run_id)

    settle_monitor_followup(_state(artifacts_dir))

    run = _run(run_id)
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    assert run["settled_by"] == "owner"
    assert not [
        n for n in load_notifications(include_dismissed=True) if n.sender == "tool-run"
    ]


def test_resumed_monitor_settlement_also_reconciles(tmp_path: Path) -> None:
    run_id = _monitor_owned_running_run()
    artifacts_dir = _make_monitor(
        tmp_path,
        run_id,
        monitor_followup_outcome="none",
        stopped_at="2026-09-06T12:00:00",
    )

    settle_monitor_followup(_state(artifacts_dir))

    assert _run(run_id)["state"] == "failed"


def test_monitor_without_a_tool_run_is_untouched(tmp_path: Path) -> None:
    run_id = _monitor_owned_running_run()
    artifacts_dir = _make_monitor(tmp_path, "", monitor_followup_outcome="none")

    settle_monitor_followup(_state(artifacts_dir))

    assert _run(run_id)["state"] == "running"
