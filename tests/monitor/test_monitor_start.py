"""End-to-end lifecycle tests for :func:`sase.monitor.start.start_monitor`.

Supervisor-process behavior, duplicate-start rejection, failure teardown, and
handoff markers live in the sibling ``test_monitor_start_*`` modules.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.monitor.models import MonitorAlreadyRunningError, MonitorRecord
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    wait_for_done,
    write_project_file,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_start_monitor_promotes_a_bare_lane_and_runs_to_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    request = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        idle_timeout_seconds=10.0,
        cwd=str(tmp_path),
        project_name="proj",
        lane="acme",
    )

    record = start_monitor(request)

    assert record.monitor_state == "running"
    assert record.member_agent_name == "acme--mon"
    assert record.lane == "acme"
    assert record.idle_timeout_seconds == 10.0

    # The starter is now a promoted family root.
    starter_meta = json.loads((Path(starter_dir) / "agent_meta.json").read_text())
    assert starter_meta["agent_family"] == "acme"
    assert starter_meta["name"] == "acme--0"

    done = wait_for_done(record.artifacts_dir)
    assert done["monitor_state"] == "completed"
    assert done["monitor_exit_code"] == 0

    # No next action: the transferred claim is released once the command
    # finishes.
    assert get_claimed_workspaces(project_file) == []


def test_start_monitor_serializes_concurrent_starts_in_one_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.monitor import store as store_module

    write_project_file("proj")
    make_starter_agent(
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

    def dynamic_project_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[AgentArtifactRecordWire]:
        records: list[AgentArtifactRecordWire] = []
        projects_root = sase_projects_dir()
        project_names = [project_name] if project_name else ["proj"]
        for name in project_names:
            artifacts_root = projects_root / name / "artifacts" / "ace-run"
            for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
                record = record_from_disk(meta_path.parent)
                if only_monitors and (
                    record.agent_meta is None
                    or record.agent_meta.agent_family_role != "monitor"
                ):
                    continue
                records.append(record)
        return records

    monkeypatch.setattr(store_module, "_project_records", dynamic_project_records)

    barrier = threading.Barrier(3)
    records: list[MonitorRecord] = []
    expected_errors: list[str] = []
    unexpected_errors: list[BaseException] = []

    def worker(command: str) -> None:
        request = StartMonitorRequest(
            command=command,
            reason="verify",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
        barrier.wait()
        try:
            records.append(start_monitor(request))
        except MonitorAlreadyRunningError as exc:
            expected_errors.append(str(exc))
        except BaseException as exc:
            unexpected_errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("sleep 2",)),
        threading.Thread(target=worker, args=("sleep 3",)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10.0)

    if unexpected_errors:
        raise unexpected_errors[0]
    assert [thread.is_alive() for thread in threads] == [False, False]
    assert len(records) == 1
    assert len(expected_errors) == 1
    assert "already has an active monitor" in expected_errors[0]

    monitor_meta_paths = [
        p
        for p in (sase_projects_dir() / "proj" / "artifacts" / "ace-run").glob(
            "*/*/*/agent_meta.json"
        )
        if json.loads(p.read_text()).get("agent_family_role") == "monitor"
    ]
    assert len(monitor_meta_paths) == 1
    wait_for_done(records[0].artifacts_dir)
