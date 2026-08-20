"""Implicit-target tests for the ``sase monitor start`` handler."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import dispatch, monitor_home, pin_project
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = ["monitor_home"]


def test_start_implicit_numeric_phase_uses_caller_workspace_without_agent_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A numeric phase name must not inherit a sibling or land artifact."""
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
    patch_project_records(monkeypatch, [caller_dir, land_dir])
    pin_project(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "sase-m6.6.1.5")

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify implicit phase",
            "-t",
            "30s",
            "--json",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    monitor = payload["monitor"]
    assert monitor["lane"] == "sase-m6.6.1.5"
    assert monitor["member_agent_name"] == "sase-m6.6.1.5--mon"
    assert monitor["cwd"] == str(caller_ws)
    meta = json.loads(Path(monitor["artifacts_dir"], "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 12
    assert meta["model"] == "caller-model"
    land_meta = json.loads(Path(land_dir, "agent_meta.json").read_text())
    assert land_meta["name"] == "sase-m6.10"
    assert "agent_family" not in land_meta


def test_start_implicit_family_member_uses_caller_workspace_without_agent_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A family member must not inherit a newer settled monitor's workspace."""
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
    pin_project(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "02i--code")

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify implicit family member",
            "-t",
            "30s",
            "--json",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    monitor = payload["monitor"]
    assert monitor["lane"] == "02i"
    assert monitor["member_agent_name"].startswith("02i--mon")
    assert monitor["cwd"] == str(caller_ws)
    meta = json.loads(Path(monitor["artifacts_dir"], "agent_meta.json").read_text())
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 12
    assert meta["model"] == "caller-model"
    settled_meta = json.loads(Path(settled_dir, "agent_meta.json").read_text())
    assert settled_meta["name"] == "02i--mon-6"
    assert settled_meta["workspace_num"] == 0


def test_start_implicit_family_container_derives_cwd_from_the_live_member(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``-C/--cwd``: the cwd comes from the caller's own live member."""
    caller_ws = tmp_path / "ws12"
    caller_ws.mkdir()
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
        workspace_dir=str(caller_ws),
        workspace_num=12,
        pid=os.getpid(),
        cl_name="046",
    )
    patch_project_records(monkeypatch, [plan_dir, code_dir])
    pin_project(monkeypatch)
    monkeypatch.setenv("SASE_AGENT_NAME", "046")

    exit_code = dispatch(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify implicit family-container cwd",
            "-t",
            "30s",
            "--json",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    monitor = payload["monitor"]
    assert monitor["lane"] == "046"
    assert monitor["cwd"] == str(caller_ws)
