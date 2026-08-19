"""Lane and parent pinning in :func:`sase.monitor.start.start_monitor`.

A start request either names its lane explicitly or leaves it implicit, in
which case the caller's own identity -- ``SASE_AGENT_NAME``,
``SASE_ARTIFACTS_DIR``, and the cwd it runs from -- decides which agent the
monitor attaches to. These tests pin that choice against the near misses:
siblings, land agents, newer settled monitors, and newer family members.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.running_field import WorkspaceClaim

from ._fixtures import (
    make_starter_agent,
    patch_project_records,
    wait_for_done,
    write_project_file,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


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
            start_status="MONITORING",
            stop_status="MONITORED",
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
            start_status="MONITORING",
            stop_status="MONITORED",
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
            start_status="MONITORING",
            stop_status="MONITORED",
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
            start_status="MONITORING",
            stop_status="MONITORED",
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
            start_status="MONITORING",
            stop_status="MONITORED",
            lane="02i",
            inherit_lane_workspace_claim=False,
        )
    )

    assert record.lane == "02i"
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812140000"
    assert meta["model"] == "newer-model"
    wait_for_done(record.artifacts_dir)
