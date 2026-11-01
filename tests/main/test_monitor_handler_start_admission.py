"""Legacy ``sase monitor start`` admits the handoff slot before spawning."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.staged_handoff import STAGING_RESERVATION_FILENAME
from sase.core.process_identity import process_identity_token
from sase.main.monitor.start import handle_monitor_start
from sase.monitor import MonitorError
from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import monitor_home, pin_project
from tests.main.parser_cli_helpers import parse_sase_args
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = ["monitor_home"]


def _start_in_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[str, list[str]]:
    write_project_file(
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
    pin_project(monkeypatch)
    monkeypatch.setenv("SASE_AGENT", "acme")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    kills: list[str] = []

    def _record_kill(artifacts_dir: str) -> None:
        kills.append(artifacts_dir)

    monkeypatch.setattr("sase.main.utils.kill_agent_runner_group", _record_kill)
    return starter_dir, kills


def _start_args(tmp_path: Path):
    return parse_sase_args(
        [
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify",
            "-t",
            "30s",
            "-a",
            "acme",
            "-C",
            str(tmp_path),
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ]
    )


def _fake_record(tmp_path: Path, request: object) -> SimpleNamespace:
    return SimpleNamespace(
        monitor_id="m" * 40,
        member_agent_name="acme--mon",
        artifacts_dir=str(tmp_path / "member"),
        lane="acme",
        project_name="proj",
        command=getattr(request, "command", "true"),
        cwd=getattr(request, "cwd", str(tmp_path)),
        next_action=None,
        next_model=None,
        next_output="full",
        request_fingerprint="fp",
        tool_run_id=None,
        monitor_state="running",
    )


def test_occupied_slot_refuses_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    starter_dir, kills = _start_in_agent(monkeypatch, tmp_path)
    pid = os.getpid()
    (Path(starter_dir) / STAGING_RESERVATION_FILENAME).write_text(
        json.dumps(
            {
                "reservation_id": "live-owner",
                "pid": pid,
                "process_identity": process_identity_token(pid),
            }
        ),
        encoding="utf-8",
    )
    started: list[object] = []

    def _boom_if_called(request: object) -> object:
        started.append(request)
        raise AssertionError("start_monitor must not run when the slot is occupied")

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", _boom_if_called)

    assert handle_monitor_start(_start_args(tmp_path)) == 1
    captured = capsys.readouterr()
    assert started == []
    assert kills == []
    assert "pending handoff already exists" in captured.err
    assert f"owner pid {pid}, alive" in captured.err
    assert (Path(starter_dir) / STAGING_RESERVATION_FILENAME).is_file()


def test_handoff_race_stops_the_spawned_monitor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _start_in_agent(monkeypatch, tmp_path)
    started: list[object] = []
    stopped: list[object] = []

    def _fake_start(request: object) -> SimpleNamespace:
        started.append(request)
        return _fake_record(tmp_path, request)

    def _fail_handoff(_record: object) -> bool:
        raise MonitorError("pending handoff already exists: .sase_plan_pending")

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", _fake_start)
    monkeypatch.setattr(
        "sase.main.monitor.start.maybe_handoff_monitor_from_agent",
        _fail_handoff,
    )
    monkeypatch.setattr(
        "sase.main.monitor.start.stop_monitor",
        lambda record: stopped.append(record) or record,
    )

    assert handle_monitor_start(_start_args(tmp_path)) == 1
    captured = capsys.readouterr()
    assert len(started) == 1
    assert len(stopped) == 1
    assert stopped[0].monitor_id == "m" * 40
    assert "pending handoff already exists" in captured.err
    assert "stopped monitor" in captured.err
    assert "after failed handoff" in captured.err
