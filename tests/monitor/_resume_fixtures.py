"""Shared fixtures for manual monitor resume tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
import sase.monitor.outcome_policy as outcome_policy_module
import sase.procs.spawn as spawn_module
from sase.agent._family_attach_types import FamilyAttachLaunchPlan
from sase.agent.launch_types import AgentLaunchResult
from sase.continuation_capture._storage import continuation_root, sha_json
from sase.monitor.models import MonitorRecord
from sase.monitor.result_projection import build_monitor_result_wire
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.procs.runtime import proc_started_path, write_json_atomic
from sase.running_field import WorkspaceClaim

from ._fixtures import make_starter_agent, record_from_disk, write_project_file


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


class _FakeSupervisorPid:
    pid = 4242424

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


def _terminal_monitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, MonitorRecord, dict[str, Any]]:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )

    def fake_popen(*args: object, **kwargs: object) -> _FakeSupervisorPid:
        argv = args[0]
        assert isinstance(argv, list)
        proc_id = argv[argv.index("--proc-id") + 1]
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple)
        pid_fd = pass_fds[0]
        assert isinstance(pid_fd, int)
        os.write(pid_fd, json.dumps({"pid": _FakeSupervisorPid.pid}).encode() + b"\n")
        write_json_atomic(proc_started_path(proc_id), {"pid": _FakeSupervisorPid.pid})
        return _FakeSupervisorPid()

    monkeypatch.setattr(spawn_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        outcome_policy_module,
        "freeze_start_outcome_policy",
        lambda *args, **kwargs: None,
    )
    starter = make_starter_agent(
        "proj",
        "20260912120000",
        "acme",
        agent_family="acme",
        workspace_num=3,
        workspace_dir=str(tmp_path),
        cl_name="acme",
    )

    def fake_resolve_plan(*args: object, **kwargs: object) -> FamilyAttachLaunchPlan:
        del args, kwargs
        return FamilyAttachLaunchPlan(
            parent_arg="acme",
            suffix_arg="@",
            parent_name="acme--0",
            parent_base="acme",
            parent_timestamp="20260912120000",
            parent_artifacts_dir=starter,
            role_suffix="--1",
            agent_name="acme--1",
            agent_family_role="code",
            parent_family_member_name="acme--0",
            parent_family_role_suffix="--0",
            parent_needs_rename=False,
            parent_project_name="proj",
            parent_is_running=False,
            parent_cl_name="acme",
            parent_workspace_dir=str(tmp_path),
            parent_workspace_num=3,
        )

    monkeypatch.setattr(
        followup_module, "resolve_family_attach_plan", fake_resolve_plan
    )

    started = start_monitor(
        StartMonitorRequest(
            command="just check",
            reason="verify",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            start_status="TESTING",
            stop_status="TESTED",
            lane="acme",
            next_action="fix the failure",
            next_output="auto",
            transfer_claim_from_pid=os.getpid(),
        )
    )
    (Path(starter) / "done.json").write_text(
        json.dumps({"outcome": "done", "name": "acme"}),
        encoding="utf-8",
    )
    monitor_dir = started.artifacts_dir
    meta_path = Path(monitor_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "monitor_state": "failed",
            "monitor_settled": True,
            "monitor_exit_code": 1,
            "monitor_elapsed_seconds": 60.0,
            "run_started_at": "2026-09-12T12:00:00+00:00",
            "stopped_at": "2026-09-12T12:01:00+00:00",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monitor_id = str(meta["monitor_id"])
    (Path(monitor_dir) / "live_reply.md").write_text(
        "FAILED_SENTINEL\n",
        encoding="utf-8",
    )
    result = build_monitor_result_wire(
        monitor_id=monitor_id,
        monitor_state="failed",
        exit_code=1,
        command="just check",
        cwd=str(tmp_path),
        started_at="2026-09-12T12:00:00+00:00",
        stopped_at="2026-09-12T12:01:00+00:00",
        elapsed_seconds=60.0,
        timeout_seconds=30.0,
        starter_execution_id="20260912120000",
        workspace_identity=str(tmp_path),
        retained_log={
            "log_ref": "local:continuation/logs/abc123def456.txt",
            "total_observed_bytes": 16,
            "complete": True,
            "drain_confirmed": True,
        },
        result_seed_extra={"frozen": "sentinel"},
    )
    result_path = (
        continuation_root(monitor_dir)
        / "records"
        / "monitor_result"
        / f"{result['result_id']}.json"
    )
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    meta["continuation_monitor_result_id"] = result["result_id"]
    meta["continuation_monitor_result_path"] = str(result_path)
    meta["continuation_monitor_result_sha256"] = sha_json(result)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return monitor_dir, MonitorRecord.from_record(record_from_disk(monitor_dir)), meta


def _fake_spawn(captured: list[dict[str, Any]]) -> Any:
    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.append(kwargs)
        return AgentLaunchResult(
            pid=1111,
            workspace_num=3,
            workspace_dir="/tmp/work",
            output_path="/tmp/out.txt",
            agent_name="acme--1",
        )

    return fake_spawn
