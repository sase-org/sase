"""Tests for :mod:`sase.monitor.member`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.monitor.member import create_monitor_member


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_create_monitor_member_inherits_lineage_and_sets_monitor_fields() -> None:
    base_meta = {
        "name": "acme--0",
        "model": "claude-sonnet-5",
        "llm_provider": "claude",
        "workspace_dir": "/work/acme",
        "cl_name": "acme",
        "bead_id": "sase-kp",
        "tribe": "sase",
        "agent_family": "acme",
        "agent_clan": "acme-clan",
        "agent_clan_generation": "20260812115000",
        "vcs_ref": ["gh", "sase"],
    }

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=3,
        monitor_id="abc123def456",
        command="just check-full",
        cwd="/work/acme",
        label="just check-full",
        reason="verify the refactor",
        next_action="Fix anything the check reported.",
        next_model="@small",
        start_status="MONITORING",
        stop_status="MONITORED",
        timeout_seconds=2700.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
        idle_timeout_seconds=600.0,
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())

    assert meta["name"] == "acme--mon"
    assert meta["workflow_name"] == "acme"
    assert meta["agent_family"] == "acme"
    assert meta["agent_family_role"] == "monitor"
    assert meta["agent_clan"] == "acme-clan"
    assert meta["agent_clan_generation"] == "20260812115000"
    assert meta["role_suffix"] == "--mon"
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 3

    # Inherited lineage from the selected parent artifact.
    assert meta["model"] == "claude-sonnet-5"
    assert meta["llm_provider"] == "claude"
    assert meta["workspace_dir"] == "/work/acme"
    assert meta["cl_name"] == "acme"
    assert meta["bead_id"] == "sase-kp"
    assert meta["tribe"] == "sase"
    assert meta["vcs_ref"] == ["gh", "sase"]

    # Monitor-specific fields.
    assert meta["monitor_id"] == "abc123def456"
    assert meta["proc_id"] == "abc123def456"
    assert meta["pid"] is None
    assert meta["shell_kind"] == "proc"
    assert meta["monitor_command"] == "just check-full"
    assert meta["monitor_cwd"] == "/work/acme"
    assert meta["monitor_label"] == "just check-full"
    assert meta["monitor_reason"] == "verify the refactor"
    assert meta["monitor_next_action"] == "Fix anything the check reported."
    assert meta["monitor_next_model"] == "@small"
    assert meta["monitor_start_status"] == "MONITORING"
    assert meta["monitor_stop_status"] == "MONITORED"
    assert meta["monitor_timeout_seconds"] == 2700.0
    assert meta["monitor_tail_lines"] == 200
    assert meta["monitor_next_output"] == "tail"
    assert meta["monitor_idle_timeout_seconds"] == 600.0
    assert meta["monitor_state"] == "running"
    assert meta["monitor_settled"] is False
    assert meta["monitor_request_fingerprint"] == "sha256:test"
    assert "monitor_execution_argv" not in meta


def test_create_monitor_member_persists_execution_argv() -> None:
    artifacts_dir = create_monitor_member(
        "proj",
        {"name": "acme--0", "agent_family": "acme"},
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="sase bead work plan.md --yes-to-all",
        cwd="/work/acme",
        label="Epic launch · plan",
        reason="Launch the approved epic from plan.md",
        next_action=None,
        start_status="EPIC APPROVED",
        stop_status="EPIC CREATED",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
        execution_argv=[
            "/usr/bin/python",
            "bootstrap.py",
            "--",
            "sase",
            "bead",
            "work",
        ],
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_command"] == "sase bead work plan.md --yes-to-all"
    assert meta["monitor_execution_argv"] == [
        "/usr/bin/python",
        "bootstrap.py",
        "--",
        "sase",
        "bead",
        "work",
    ]


def test_create_monitor_member_omits_next_action_when_none() -> None:
    base_meta = {"name": "acme--0", "agent_family": "acme"}

    artifacts_dir = create_monitor_member(
        "proj",
        base_meta,
        lane="acme",
        suffix="--mon",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=0,
        monitor_id="abc123def456",
        command="sleep 5",
        cwd="/work/acme",
        label="sleep",
        reason="wait",
        next_action=None,
        start_status="SLEEPING",
        stop_status="SLEPT",
        timeout_seconds=30.0,
        tail_lines=200,
        next_output="tail",
        request_fingerprint="sha256:test",
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert "monitor_next_action" not in meta
    assert "monitor_next_model" not in meta
    assert "monitor_idle_timeout_seconds" not in meta
    assert "agent_clan" not in meta
    assert "agent_clan_generation" not in meta
