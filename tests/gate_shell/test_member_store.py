"""Gate-shell member artifact creation and direct projection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.gate_shell.member import create_gate_shell_member
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
    assert meta["proc_id"] is None

    record = read_gate_shell_marker("proj", artifacts_dir)
    assert record is not None
    assert record.gate_id == "gate-1"
    assert record.member_agent_name == "lane--gate"
    assert record.status_bucket == "Stopped"
    assert record.next_action == "continue"
    assert record.next_fork == "shell"
    assert record.next_output == "results,tail"
