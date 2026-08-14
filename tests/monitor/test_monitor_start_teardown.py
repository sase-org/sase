"""Failure teardown in :func:`sase.monitor.start.start_monitor`.

When a start cannot reach a running supervisor, the half-created member agent
must be finalized as failed rather than left behind as a phantom.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.core.paths import sase_projects_dir
from sase.monitor.models import MonitorError
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, patch_project_records, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_start_monitor_tears_down_the_member_when_the_supervisor_cannot_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    import sase.monitor.spawn as spawn_module

    def fake_popen(*args: object, **kwargs: object) -> None:
        raise OSError("no more processes")

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorError):
        start_monitor(request)

    # The half-created member is marked failed, not left phantom-running.
    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    done = json.loads((member_dirs[0] / "done.json").read_text())
    assert done["monitor_state"] == "failed"
    assert done["project_file"] == str(sase_projects_dir() / "proj" / "proj.sase")

    # create_followup_artifacts() seeded workflow_state.json with
    # status="running" and appears_as_agent=True; teardown must finalize it
    # rather than leave it permanently non-terminal.
    workflow_state = json.loads((member_dirs[0] / "workflow_state.json").read_text())
    assert workflow_state["status"] == "completed"
    assert workflow_state["appears_as_agent"] is True


def test_start_monitor_claim_failure_does_not_run_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "command-ran"
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=123456)],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    request = StartMonitorRequest(
        command=f"touch {sentinel}",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    with pytest.raises(MonitorError, match="could not claim workspace"):
        start_monitor(request)

    assert not sentinel.exists()
    artifacts_root = sase_projects_dir() / "proj" / "artifacts" / "ace-run"
    member_dirs = [
        p.parent
        for p in artifacts_root.glob("*/*/*/agent_meta.json")
        if p.parent != Path(starter_dir)
    ]
    assert len(member_dirs) == 1
    meta = json.loads((member_dirs[0] / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_settled"] is True
    assert "monitor_pgid" not in meta
    done = json.loads((member_dirs[0] / "done.json").read_text())
    assert done["monitor_state"] == "failed"
