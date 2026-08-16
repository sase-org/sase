"""End-to-end lifecycle tests for :func:`sase.monitor.start.start_monitor`.

Supervisor-process behavior, duplicate-start rejection, failure teardown, and
handoff markers live in the sibling ``test_monitor_start_*`` modules.
"""

from __future__ import annotations

import json
import os
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import sase.monitor.followup as followup_module
from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_scan_wire_records import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.monitor.models import MonitorAlreadyRunningError, MonitorError, MonitorRecord
from sase.monitor.output import OutputCapture
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import (
    WorkspaceClaim,
    claim_next_axe_workspace,
    get_claimed_workspaces,
    transfer_workspace_claim,
)

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    register_workspace_checkout,
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


def test_start_monitor_without_metadata_workspace_num_claims_the_cwd_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    project_file = write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(10, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=workspace_dir,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 30",
            reason="verify missing metadata workspace number",
            timeout_seconds=30.0,
            cwd=workspace_dir,
            project_name="proj",
            lane="acme",
        )
    )

    try:
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workspace_num == 10
        assert claims[0].pid == record.pid
        assert claims[0].workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW
        assert claims[0].cl_name == "acme"

        meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
        assert meta["workspace_num"] == 10
        assert meta["workspace_dir"] == workspace_dir
    finally:
        if record.pid is not None:
            try:
                os.kill(record.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        wait_for_done(record.artifacts_dir, timeout=10.0)


def test_monitor_claim_survives_stale_cleanup_allocation_and_followup_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    project_file = write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(10, "ace-run", "acme", pid=111111)],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=workspace_dir,
        pid=111111,
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="sleep 120",
            reason="verify claim invariant replay",
            timeout_seconds=120.0,
            cwd=workspace_dir,
            project_name="proj",
            lane="acme",
            next_action="Inspect the result.",
        )
    )
    supervisor_pid = record.pid
    assert supervisor_pid is not None

    try:
        (Path(starter_dir) / "done.json").write_text(
            json.dumps({"outcome": "monitored"}),
            encoding="utf-8",
        )
        claims = get_claimed_workspaces(project_file)
        assert [
            (claim.workspace_num, claim.pid, claim.workflow) for claim in claims
        ] == [(10, supervisor_pid, MONITOR_WORKSPACE_CLAIM_WORKFLOW)]

        monkeypatch.setattr(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            lambda: [project_file],
        )
        monkeypatch.setattr(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            lambda pid: pid == supervisor_pid,
        )

        assert cleanup_stale_running_entries() == 0
        allocated = claim_next_axe_workspace(
            project_file,
            "ace(run)-260814_121212",
            pid=444444,
            cl_name="new-agent",
            artifacts_timestamp="260814_121212",
            min_workspace=10,
            max_workspace=11,
        )
        assert allocated == 11

        @dataclass(frozen=True)
        class FollowupPlan:
            agent_name: str = "acme--1"
            parent_is_running: bool = False
            agent_family_role: str = "root"
            parent_workspace_dir: str = workspace_dir
            parent_workspace_num: int = 10

        followup_pid = 333333
        captured_spawn: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured_spawn.update(kwargs)
            result = transfer_workspace_claim(
                project_file,
                10,
                from_pid=kwargs["retry_transfer_from_pid"],
                to_pid=followup_pid,
                new_workflow=kwargs["workflow_name"],
                new_artifacts_timestamp=kwargs["timestamp"],
                cl_name=kwargs["cl_name"],
            )
            assert result.success, result.error
            return AgentLaunchResult(
                pid=followup_pid,
                workspace_num=10,
                workspace_dir=workspace_dir,
                output_path=str(tmp_path / "followup.out"),
                agent_name="acme--1",
            )

        monkeypatch.setattr(
            followup_module,
            "resolve_family_attach_plan",
            lambda *_args, **_kwargs: FollowupPlan(),
        )
        monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

        monitor_meta = json.loads(
            (Path(record.artifacts_dir) / "agent_meta.json").read_text()
        )
        capture = OutputCapture()
        result = followup_module.launch_followup_agent(
            record.artifacts_dir,
            monitor_meta,
            monitor_state="completed",
            exit_code=0,
            elapsed_seconds=1.0,
            capture=capture,
            project_name="proj",
            settle_timeout_seconds=0.0,
            transfer_from_pid=supervisor_pid,
        )

        assert result.launched is True
        assert captured_spawn["workspace_dir"] == workspace_dir
        assert captured_spawn["workspace_num"] == 10
        assert captured_spawn["retry_transfer_from_pid"] == supervisor_pid
        claims_by_num = {
            claim.workspace_num: claim for claim in get_claimed_workspaces(project_file)
        }
        assert claims_by_num[10].pid == followup_pid
        assert claims_by_num[11].workflow.startswith("ace(run)-")
    finally:
        if record.pid is not None:
            try:
                os.kill(record.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        wait_for_done(record.artifacts_dir, timeout=10.0)


def test_start_monitor_refuses_a_numbered_cwd_claimed_by_another_live_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 11)
    project_file = write_project_file(
        "proj",
        workspace_dir=str(primary),
        running_claims=[WorkspaceClaim(11, "ace-run", "other", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(primary),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    before_claims = get_claimed_workspaces(project_file)
    sentinel = tmp_path / "command-ran"

    request = StartMonitorRequest(
        command=f"touch {sentinel}",
        reason="verify conflict refusal",
        timeout_seconds=30.0,
        cwd=workspace_dir,
        project_name="proj",
        lane="acme",
        inherit_lane_workspace_claim=False,
    )

    with pytest.raises(MonitorError, match=r"workspace #11.*other"):
        start_monitor(request)

    assert not sentinel.exists()
    assert get_claimed_workspaces(project_file) == before_claims


def test_start_monitor_epic_launch_from_non_numbered_cwd_uses_workspace_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    project_file = write_project_file("proj", workspace_dir=str(primary))
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--0",
        agent_family="acme",
        model="claude-sonnet-5",
        workspace_dir=str(primary),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify non-numbered cwd",
            timeout_seconds=30.0,
            cwd=str(outside),
            project_name="proj",
            lane="acme",
            inherit_lane_workspace_claim=False,
        )
    )

    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["workspace_num"] == 0
    assert meta["workspace_dir"] == str(outside)
    wait_for_done(record.artifacts_dir)
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


def test_implicit_start_pins_numeric_phase_caller_not_sibling_or_land(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
    other_ws = tmp_path / "primary"
    other_ws.mkdir()
    write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(12, "ace-run", "sase-m6.6.1.5", pid=os.getpid())
        ],
    )
    caller_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "sase-m6.6.1.5",
        model="caller-model",
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="sase-m6.6.1.5",
    )
    sibling_dir = make_starter_agent(
        "proj",
        "20260812125000",
        "sase-m6.6.1",
        model="sibling-model",
        workspace_dir=str(other_ws),
        workspace_num=7,
        pid=os.getpid(),
        cl_name="sase-m6.6.1",
    )
    land_dir = make_starter_agent(
        "proj",
        "20260812130000",
        "sase-m6.10",
        model="land-model",
        workspace_dir=str(other_ws),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="sase-m6.10",
    )
    patch_project_records(monkeypatch, [caller_dir, sibling_dir, land_dir])
    monkeypatch.setenv("SASE_AGENT_NAME", "sase-m6.6.1.5")

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify implicit numeric phase identity",
            timeout_seconds=30.0,
            cwd=str(caller_ws),
            project_name="proj",
        )
    )

    assert record.lane == "sase-m6.6.1.5"
    assert record.member_agent_name == "sase-m6.6.1.5--mon"
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 12
    assert meta["workspace_dir"] == str(caller_ws)
    assert meta["model"] == "caller-model"
    assert meta["agent_family"] == "sase-m6.6.1.5"

    caller_meta = json.loads((Path(caller_dir) / "agent_meta.json").read_text())
    assert caller_meta["name"] == "sase-m6.6.1.5--0"
    assert caller_meta["agent_family"] == "sase-m6.6.1.5"
    sibling_meta = json.loads((Path(sibling_dir) / "agent_meta.json").read_text())
    land_meta = json.loads((Path(land_dir) / "agent_meta.json").read_text())
    assert sibling_meta["name"] == "sase-m6.6.1"
    assert "agent_family" not in sibling_meta
    assert land_meta["name"] == "sase-m6.10"
    assert "agent_family" not in land_meta

    wait_for_done(record.artifacts_dir)


def test_implicit_start_pins_family_member_not_newer_settled_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
    primary = tmp_path / "primary"
    primary.mkdir()
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(12, "ace-run", "02i", pid=os.getpid())],
    )
    caller_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "02i--code",
        agent_family="02i",
        model="caller-model",
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="02i",
    )
    settled_dir = make_starter_agent(
        "proj",
        "20260812140000",
        "02i--mon-6",
        agent_family="02i",
        agent_family_role="monitor",
        monitor_id="oldmon123456",
        monitor_state="completed",
        monitor_settled=True,
        monitor_command="just check-full",
        model="monitor-model",
        workspace_dir=str(primary),
        workspace_num=0,
        cl_name="02i",
    )
    patch_project_records(monkeypatch, [caller_dir, settled_dir])
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify implicit family-member identity",
            timeout_seconds=30.0,
            cwd=str(caller_ws),
            project_name="proj",
        )
    )

    assert record.lane == "02i"
    assert record.member_agent_name.startswith("02i--mon")
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 12
    assert meta["workspace_dir"] == str(caller_ws)
    assert meta["model"] == "caller-model"
    assert meta["agent_family"] == "02i"

    caller_meta = json.loads((Path(caller_dir) / "agent_meta.json").read_text())
    settled_meta = json.loads((Path(settled_dir) / "agent_meta.json").read_text())
    assert caller_meta["name"] == "02i--code"
    assert caller_meta["agent_family"] == "02i"
    assert settled_meta["name"] == "02i--mon-6"
    assert settled_meta["workspace_num"] == 0

    wait_for_done(record.artifacts_dir)


def test_implicit_start_from_a_promoted_family_container_pins_the_live_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_AGENT_NAME`` naming the family container pins the live member."""
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
    primary = tmp_path / "primary"
    primary.mkdir()
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(12, "ace-run", "046", pid=os.getpid())],
    )
    plan_dir = make_starter_agent(
        "proj",
        "20260812110000",
        "046--plan",
        agent_family="046",
        model="plan-model",
        workspace_dir=str(primary),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="046",
    )
    (Path(plan_dir) / "done.json").write_text(
        json.dumps({"outcome": "done"}), encoding="utf-8"
    )
    code_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "046--code",
        agent_family="046",
        model="caller-model",
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="046",
    )
    settled_dir = make_starter_agent(
        "proj",
        "20260812140000",
        "046--mon-6",
        agent_family="046",
        agent_family_role="monitor",
        monitor_id="oldmon123456",
        monitor_state="completed",
        monitor_settled=True,
        monitor_command="just check-full",
        model="monitor-model",
        workspace_dir=str(primary),
        workspace_num=0,
        cl_name="046",
    )
    patch_project_records(monkeypatch, [plan_dir, code_dir, settled_dir])
    monkeypatch.setenv("SASE_AGENT_NAME", "046")

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify implicit family-container identity",
            timeout_seconds=30.0,
            cwd=str(caller_ws),
            project_name="proj",
        )
    )

    assert record.lane == "046"
    assert record.member_agent_name.startswith("046--mon")
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 12
    assert meta["workspace_dir"] == str(caller_ws)
    assert meta["model"] == "caller-model"
    assert meta["agent_family"] == "046"

    code_meta = json.loads((Path(code_dir) / "agent_meta.json").read_text())
    settled_meta = json.loads((Path(settled_dir) / "agent_meta.json").read_text())
    assert code_meta["name"] == "046--code"
    assert code_meta["agent_family"] == "046"
    assert settled_meta["name"] == "046--mon-6"
    assert settled_meta["workspace_num"] == 0

    wait_for_done(record.artifacts_dir)


def test_implicit_start_pins_the_callers_artifacts_dir_over_a_newer_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller's own ``SASE_ARTIFACTS_DIR`` outranks a newer family member."""
    write_project_file("proj")
    plan_dir = make_starter_agent(
        "proj",
        "20260812110000",
        "046--plan",
        agent_family="046",
        model="plan-model",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="046",
    )
    code_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "046--code",
        agent_family="046",
        model="caller-model",
        workspace_dir=str(tmp_path),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="046",
    )
    patch_project_records(monkeypatch, [plan_dir, code_dir])
    monkeypatch.setenv("SASE_AGENT_NAME", "046")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", plan_dir)

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify implicit artifacts-dir pin",
            timeout_seconds=30.0,
            cwd=str(tmp_path),
            project_name="proj",
            inherit_lane_workspace_claim=False,
        )
    )

    assert record.lane == "046"
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812110000"
    assert meta["model"] == "plan-model"

    wait_for_done(record.artifacts_dir)


def test_explicit_family_target_still_selects_newest_lane_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older_ws = tmp_path / "ws12"
    older_ws.mkdir()
    newer_ws = tmp_path / "ws0"
    newer_ws.mkdir()
    write_project_file("proj")
    older_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "02i--code",
        agent_family="02i",
        model="older-model",
        workspace_dir=str(older_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="02i",
    )
    newer_dir = make_starter_agent(
        "proj",
        "20260812140000",
        "02i--review",
        agent_family="02i",
        model="newer-model",
        workspace_dir=str(newer_ws),
        workspace_num=0,
        pid=os.getpid(),
        cl_name="02i",
    )
    patch_project_records(monkeypatch, [older_dir, newer_dir])

    record = start_monitor(
        StartMonitorRequest(
            command="true",
            reason="verify explicit family target",
            timeout_seconds=30.0,
            cwd=str(newer_ws),
            project_name="proj",
            lane="02i",
            inherit_lane_workspace_claim=False,
        )
    )

    assert record.lane == "02i"
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812140000"
    assert meta["model"] == "newer-model"
    wait_for_done(record.artifacts_dir)
