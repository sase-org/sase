"""Gate-shell member artifact creation and direct projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    FamilyShellGateWire,
    FamilyShellWire,
)
from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.models import GateShellRecord
import sase.gate_shell.store as gate_store
from sase.gate_shell.store import read_gate_shell_marker
from sase.notification_gates.model_shell import GateShellSpec


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_create_gate_shell_member_projects_gate_metadata() -> None:
    shell = GateShellSpec.from_mapping(
        {
            "pending_status": "WAIT",
            "settled_status": "DONE",
            "accent": "#00D7AF",
            "next": {
                "prompt": "continue",
                "fork": "shell",
                "model": "gpt-5",
                "output": ["results", "tail"],
            },
        },
        branches=(("accept",),),
    )

    artifacts_dir = create_gate_shell_member(
        "proj",
        {
            "name": "lane--0",
            "agent_family": "lane",
            "model": "gpt-5",
            "workspace_dir": "/work/lane",
            "agent_clan": "clan-a",
            "vcs_ref": ["gh", "sase"],
        },
        lane="lane",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=7,
        gate_id="gate-1",
        gate_kind="custom",
        label="Review deploy",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint="abc123",
        shell=shell,
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["name"] == "lane--gate"
    assert meta["shell_kind"] == "gate"
    assert meta["agent_family_role"] == "gate"
    assert meta["gate_id"] == "gate-1"
    assert meta["gate_state"] == "pending"
    assert meta["gate_start_status"] == "WAIT"
    assert meta["gate_stop_status"] == "DONE"
    assert meta["gate_next_action"] == "continue"
    assert meta["gate_next_fork"] == "shell"
    assert meta["gate_next_model"] == "gpt-5"
    assert meta["gate_next_output"] == "results,tail"
    assert meta["pid"] is None
    assert "process_identity" not in meta
    assert meta["proc_id"] is None
    workflow_state = json.loads(
        (Path(artifacts_dir) / "workflow_state.json").read_text()
    )
    assert workflow_state["pid"] is None
    assert "process_identity" not in workflow_state
    assert meta["vcs_ref"] == ["gh", "sase"]

    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    assert record.gate_id == "gate-1"
    assert record.member_agent_name == "lane--gate"
    assert record.status_bucket == "Stopped"
    assert record.next_action == "continue"
    assert record.next_fork == "shell"
    assert record.next_output == "results,tail"


def test_answered_handoff_gate_record_buckets_running() -> None:
    record = GateShellRecord(
        gate_id="gate-1",
        member_agent_name="lane--gate",
        lane="lane",
        project_name="proj",
        artifacts_dir="/tmp/artifacts",
        timestamp="20260828120000",
        kind="approval",
        gate_state="answered",
        start_status="TALE",
        stop_status="TALE APPROVED",
        accent="#FF87AF",
        label="Review tale",
        reason="wait",
        creator_agent="lane--0",
        bundle_path="/tmp/bundle",
        notification_id="notif-1",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )

    assert record.status_bucket == "Running"


def test_list_gate_shells_orders_tied_timestamps_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def wire(path: str) -> AgentArtifactRecordWire:
        return AgentArtifactRecordWire(
            project_name="proj",
            project_dir="/tmp/proj",
            project_file="/tmp/proj/proj.sase",
            workflow_dir_name="ace-run",
            artifact_dir=path,
            timestamp="20260812120000",
            agent_meta=AgentMetaWire(
                name=Path(path).name,
                agent_family="lane",
                agent_family_role="gate",
                family_shell=FamilyShellWire(
                    kind="gate",
                    id="gate-1",
                    state="pending",
                    gate=FamilyShellGateWire(kind="custom"),
                ),
            ),
        )

    monkeypatch.setattr(
        gate_store,
        "_project_records",
        lambda project_name: [
            wire("/tmp/proj/artifacts/ace-run/20260812120000-a"),
            wire("/tmp/proj/artifacts/ace-run/20260812120000-b"),
        ],
    )

    records = gate_store.list_gate_shells(project="proj")
    assert [record.artifacts_dir for record in records] == [
        "/tmp/proj/artifacts/ace-run/20260812120000-b",
        "/tmp/proj/artifacts/ace-run/20260812120000-a",
    ]
    assert gate_store.find_gate_shell_by_gate_id("proj", "gate-1") == records[0]
