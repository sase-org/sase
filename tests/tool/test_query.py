from __future__ import annotations

from pathlib import Path

import pytest

from sase.tool.control import monitor_output_path
from sase.tool.query import ToolShowCliRequest, handle_show


def test_show_missing_run_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    code = handle_show(ToolShowCliRequest(run_id="missing-id", json=False, logs=False))
    captured = capsys.readouterr()
    assert code == 2
    assert "not found" in captured.err or "does not exist" in captured.err


def _seed_settled(settled_ts: int) -> str:
    from sase.core.tool_run import tool_run_begin, tool_run_finish

    definition = {
        "schema_version": 1,
        "name": "seeded",
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    run_id = tool_run_begin(
        {
            "schema_version": 1,
            "definition": definition,
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "now_ts": settled_ts - 5,
        }
    )["run"]["run_id"]
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "succeeded",
            "exit_code": 0,
            "duration_ms": 5,
            "now_ts": settled_ts,
        }
    )
    return run_id


def test_show_identifies_runs_whose_detail_may_have_been_pruned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json
    import time

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    now = int(time.time())
    fresh = _seed_settled(now)
    old = _seed_settled(now - 90 * 86400)

    assert handle_show(ToolShowCliRequest(run_id=fresh, json=True, logs=False)) == 0
    assert json.loads(capsys.readouterr().out)["detail_retention"] == {
        "detail_days": 60,
        "detail_may_be_pruned": False,
    }
    assert handle_show(ToolShowCliRequest(run_id=old, json=True, logs=False)) == 0
    assert json.loads(capsys.readouterr().out)["detail_retention"] == {
        "detail_days": 60,
        "detail_may_be_pruned": True,
    }
    assert handle_show(ToolShowCliRequest(run_id=old, json=False, logs=False)) == 0
    assert "older than 60 days is pruned by retention" in capsys.readouterr().err
    assert handle_show(ToolShowCliRequest(run_id=fresh, json=False, logs=False)) == 0
    assert "pruned by retention" not in capsys.readouterr().err


def test_monitor_output_path_retries_unscoped_when_project_misses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.monitor.models import MonitorRecord

    log = tmp_path / "owner.log"
    log.write_text("hello\n", encoding="utf-8")
    record = MonitorRecord(
        monitor_id="mon-linked-1",
        member_agent_name="agent",
        lane="lane",
        project_name="host",
        artifacts_dir=str(tmp_path),
        timestamp="2026-01-01T00:00:00Z",
        command="true",
        cwd=str(tmp_path),
        reason="reason",
        label="label",
        start_status="START",
        stop_status="STOP",
        timeout_seconds=1.0,
        tail_lines=10,
        monitor_state="completed",
        output_path=str(log),
    )

    def fake_list(*, project: str | None = None) -> list[MonitorRecord]:
        if project == "linked-repo":
            return []
        return [record]

    monkeypatch.setattr("sase.monitor.store.list_monitors", fake_list)
    path = monitor_output_path({"project": "linked-repo"}, "mon-linked-1")
    assert path == log
