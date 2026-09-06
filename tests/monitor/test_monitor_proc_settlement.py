"""Unit tests for proc-backed monitor settlement ordering."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.monitor.followup import FollowupLaunchResult
from sase.monitor.proc_adapter import settle_monitor_artifacts, settle_monitor_followup
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _make_proc_monitor(
    tmp_path: Path,
    *,
    next_action: str | None = "Report that it finished.",
) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-monitor", "acme", pid=os.getpid())],
    )
    return make_starter_agent(
        "proj",
        "20260906120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="abc123def456",
        monitor_command="true",
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=30.0,
        monitor_next_action=next_action,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        shell_kind="proc",
    )


def _settlement_state(artifacts_dir: str) -> dict[str, object]:
    return {
        "artifacts_dir": artifacts_dir,
        "proc_id": "abc123def456",
        "status": "success",
        "termination_reason": "success",
        "exit_code": 0,
    }


def test_settle_monitor_artifacts_leaves_stopped_at_unpersisted(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    state = _settlement_state(artifacts_dir)

    settle_monitor_artifacts(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert "stopped_at" not in on_disk
    monitor_meta = state["monitor_meta"]
    assert isinstance(monitor_meta, dict)
    assert isinstance(monitor_meta.get("stopped_at"), str)


def test_settle_monitor_followup_persists_stopped_at_after_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path)
    followup_dir = tmp_path / "followup"
    followup_dir.mkdir()
    state = _settlement_state(artifacts_dir)
    settle_monitor_artifacts(state)
    import sase.monitor.proc_adapter as proc_adapter

    wait_calls: list[tuple[str, int | None]] = []

    def fake_launch_success(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> FollowupLaunchResult:
        on_disk = json.loads((Path(_artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert isinstance(meta.get("stopped_at"), str)
        meta["monitor_followup_agent"] = "acme--1"
        return FollowupLaunchResult(
            launched=True,
            agent_name="acme--1",
            artifacts_dir=str(followup_dir),
            pid=321,
        )

    def fake_wait(artifacts_dir_arg: str, pid: int | None) -> bool:
        on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert "stopped_at" not in on_disk
        assert not (Path(artifacts_dir) / "done.json").exists()
        wait_calls.append((artifacts_dir_arg, pid))
        return True

    monkeypatch.setattr(proc_adapter, "launch_followup_agent", fake_launch_success)
    monkeypatch.setattr(proc_adapter, "wait_for_followup_started", fake_wait)

    settle_monitor_followup(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert wait_calls == [(str(followup_dir), 321)]
    assert isinstance(on_disk.get("stopped_at"), str)
    assert on_disk["monitor_settled"] is True
    assert on_disk["monitor_followup_outcome"] == "launched"
    assert (Path(artifacts_dir) / "done.json").exists()


def test_settle_monitor_followup_sets_missing_stopped_at_on_resume(
    tmp_path: Path,
) -> None:
    artifacts_dir = _make_proc_monitor(tmp_path, next_action=None)
    state: dict[str, object] = {
        "artifacts_dir": artifacts_dir,
        "monitor_state": "completed",
        "monitor_exit_code": 0,
        "monitor_elapsed_seconds": 0.0,
        "response_path": "/tmp/response.md",
    }

    settle_monitor_followup(state)

    on_disk = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert isinstance(on_disk.get("stopped_at"), str)
    assert on_disk["monitor_settled"] is True
    assert (Path(artifacts_dir) / "done.json").exists()
