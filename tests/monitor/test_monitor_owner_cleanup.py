"""Owner cleanup stops a live proc-backed monitor and suppresses follow-up."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.core.agent_cleanup_wire import AGENT_CLEANUP_WIRE_SCHEMA_VERSION
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.store import list_monitors
from sase.ops.commands.agent import _apply_cleanup_payload_for_result
from sase.procs.store import get_proc
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, wait_for_done, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _patch_live_records(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.core.paths import sase_projects_dir
    from sase.monitor import store as store_module

    from ._fixtures import record_from_disk

    def live_records(
        project_name: str | None, *, only_monitors: bool = False
    ) -> list[object]:
        records = []
        projects_root = sase_projects_dir()
        names = [project_name] if project_name else ["proj"]
        for name in names:
            artifacts_root = projects_root / name / "artifacts" / "ace-run"
            if not artifacts_root.exists():
                continue
            for meta_path in artifacts_root.glob("*/*/*/agent_meta.json"):
                record = record_from_disk(meta_path.parent)
                if only_monitors and (
                    record.agent_meta is None
                    or record.agent_meta.agent_family_role != "monitor"
                ):
                    continue
                records.append(record)
        return records

    monkeypatch.setattr(store_module, "_project_records", live_records)


def test_owner_cleanup_stops_monitor_child_and_suppresses_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_file = write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    _patch_live_records(monkeypatch)
    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="owner cleanup should stop this command",
            timeout_seconds=60.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="acme",
            next_action="SENTINEL_NEXT should never launch",
        )
    )
    supervisor = record.pid
    assert supervisor is not None
    assert is_process_running(supervisor)

    identity = {
        "agent_type": "run",
        "cl_name": "acme--mon",
        "raw_suffix": Path(record.artifacts_dir).name,
    }
    success, message, _payload = _apply_cleanup_payload_for_result(
        {
            "action": "kill",
            "transaction": "bulk_kill",
            "cleanup_plan": {
                "schema_version": AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                "kill_items": [
                    {
                        "identity": identity,
                        "kind": "monitor",
                        "monitor_id": record.monitor_id,
                    }
                ],
                "side_effects": {
                    "monitor_stop_requests": [
                        {
                            "identity": identity,
                            "monitor_id": record.monitor_id,
                        }
                    ]
                },
            },
            "kill_items": [],
            "dismissable": [],
            "dismissed_identities": [],
        }
    )
    assert success is True, message
    done = wait_for_done(record.artifacts_dir, timeout=10.0)
    assert done["monitor_state"] == "stopped"
    deadline = time.monotonic() + 5
    while is_process_running(supervisor) and time.monotonic() < deadline:
        time.sleep(0.05)  # sase-test-wait: poll monitor supervisor exit
    assert not is_process_running(supervisor)
    proc = get_proc(record.monitor_id)
    assert proc is not None
    assert proc.status == "killed"
    meta = json.loads(
        (Path(record.artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta.get("monitor_followup_agent") is None
    assert meta.get("monitor_followup_outcome") in {None, "suppressed"}
    listed = list_monitors(project="proj")
    assert listed[0].monitor_state == "stopped"
    assert listed[0].followup_agent is None
    assert get_claimed_workspaces(project_file) == []
