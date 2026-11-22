"""Waiting-queue surfaces for host-wide check admission.

Covers ``sase tool runs`` (waiting marker), ``sase tool show`` (the
ADMISSION line), ``sase tool wait`` (timeout copy and the ``-j``
admission object), the shared escalation block, the follower
waiting/granted lines, and the stats admission-wait cell. Uses an
isolated ``SASE_HOME`` with real core admission records; no fixture
catalog runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _seed_running(tool_name: str = "check") -> str:
    from sase.core.tool_run import tool_run_begin

    definition = {
        "schema_version": 1,
        "name": tool_name,
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    return tool_run_begin(
        {
            "schema_version": 1,
            "run_id": __import__("secrets").token_hex(16),
            "tool_name": tool_name,
            "definition": definition,
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
        }
    )["run"]["run_id"]


def _enter(run_id: str, *, limit: int = 1) -> dict[str, Any]:
    from sase.core.tool_run import tool_run_admission_enter

    return tool_run_admission_enter(
        {"schema_version": 1, "run_id": run_id, "key": "check", "limit": limit}
    )


def _hold_and_queue() -> tuple[str, str]:
    holder = _seed_running()
    assert _enter(holder)["outcome"] == "admitted"
    waiter = _seed_running()
    assert _enter(waiter)["outcome"] == "waiting"
    return holder, waiter


def test_runs_marks_waiting_with_live_ahead(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.query_runs import ToolRunsCliRequest, handle_runs

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, _waiter = _hold_and_queue()

    assert (
        handle_runs(
            ToolRunsCliRequest(
                include_all=True,
                agent=None,
                cursor=None,
                json=False,
                limit=20,
                state=None,
                tool=None,
            )
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "(waiting, 0 ahead)" in out


def test_show_prints_waiting_admission_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.query import ToolShowCliRequest, handle_show

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, waiter = _hold_and_queue()

    assert handle_show(ToolShowCliRequest(run_id=waiter, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "ADMISSION waiting for a check slot since " in out
    assert "(limit 1, 0 ahead)" in out


def test_show_prints_settled_admission_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.tool_run import tool_run_admission_force, tool_run_show
    from sase.tool.executor_recording import finish_tool_run
    from sase.tool.query import ToolShowCliRequest, handle_show

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    holder, waiter = _hold_and_queue()
    forced = _seed_running()
    _enter(forced)
    tool_run_admission_force(
        {"schema_version": 1, "run_id": forced, "reason": "max_wait"}
    )
    finish_tool_run(
        holder,
        state="succeeded",
        exit_code=0,
        duration_ms=100,
        terminal_cause="exited",
    )

    assert tool_run_show(waiter)["run"]["state"] in ("running", "created")
    assert handle_show(ToolShowCliRequest(run_id=forced, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "ADMISSION admitted over limit after max wait (limit 1)" in out


def test_show_names_an_unavailable_bypass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.tool_run import tool_run_admission_force
    from sase.tool.query import ToolShowCliRequest, handle_show

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, _waiter = _hold_and_queue()
    bypass = _seed_running()
    _enter(bypass)
    result = tool_run_admission_force(
        {
            "schema_version": 1,
            "run_id": bypass,
            "reason": "unavailable",
            "key": "check",
            "limit": 1,
        }
    )
    assert result["admission"]["admitted_by"] == "unavailable"

    assert handle_show(ToolShowCliRequest(run_id=bypass, json=False, logs=False)) == 0
    assert "ADMISSION admitted through unavailable bypass" in capsys.readouterr().out


def test_show_json_carries_demand_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.tool.query import ToolShowCliRequest, handle_show

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, waiter = _hold_and_queue()

    assert handle_show(ToolShowCliRequest(run_id=waiter, json=True, logs=False)) == 0
    envelope = json.loads(capsys.readouterr().out)
    admission = (envelope["run"].get("demand") or {}).get("admission")
    assert isinstance(admission, dict)
    assert admission["state"] == "waiting"
    assert envelope.get("admission", {}).get("state") == "waiting"


def test_wait_json_carries_admission_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool._control_shared import load_run
    from sase.tool.control_wait import _wait_json

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, waiter = _hold_and_queue()

    payload = _wait_json(waiter, load_run(waiter))
    assert payload["schema_version"] == 1
    assert payload["admission"]["state"] == "waiting"
    assert payload["admission"]["key"] == "check"


def test_wait_timeout_names_the_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool._control_shared import load_run
    from sase.tool.admission_display import waiting_timeout_line

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, waiter = _hold_and_queue()

    line = waiting_timeout_line(waiter, load_run(waiter))
    assert line.startswith(f"tool run {waiter} is still waiting for a check slot")
    assert "0 ahead" in line


def test_escalation_block_names_the_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool._control_shared import load_run
    from sase.tool.routing import escalation_block

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    _holder, waiter = _hold_and_queue()
    budget = {"budget_seconds": 60, "source": "test"}

    block = escalation_block(load_run(waiter), budget, waiter)
    assert "is still waiting for a check slot" in block
    assert "0 ahead" in block


def test_follower_lines_fire_once_per_change() -> None:
    from sase.tool.follow_run import _emit_admission_lines

    emitted: list[str] = []
    state: dict[str, Any] = {"waiting": None, "granted": False}
    run = {
        "run_id": "w1",
        "state": "running",
        "demand": {"admission": {"state": "waiting", "key": "check", "limit": 1}},
    }
    envelope = {
        "run": run,
        "admission": {
            "state": "waiting",
            "key": "check",
            "limit": 1,
            "ahead": 2,
            "holders": 1,
            "requested_ts_ms": 1,
        },
    }
    _emit_admission_lines(envelope, emitted.append, state)
    assert emitted == ["sase: waiting for a check slot (limit 1: 1 running, 2 ahead)"]
    # Same position: silent.
    _emit_admission_lines(envelope, emitted.append, state)
    assert len(emitted) == 1
    # Moved position: one more line.
    envelope["admission"] = dict(envelope["admission"], ahead=1)
    _emit_admission_lines(envelope, emitted.append, state)
    assert emitted[-1] == "sase: waiting for a check slot (limit 1: 1 running, 1 ahead)"
    # Granted: exactly one granted line, then silence.
    run["demand"] = {
        "admission": {
            "state": "admitted",
            "key": "check",
            "limit": 1,
            "wait_ms": 90000,
            "admitted_by": "slot",
        }
    }
    envelope["admission"] = dict(envelope["admission"], state="admitted", ahead=0)
    _emit_admission_lines(envelope, emitted.append, state)
    assert emitted[-1] == "sase: check slot granted after 1m 30s"
    _emit_admission_lines(envelope, emitted.append, state)
    assert emitted[-1] == "sase: check slot granted after 1m 30s"


@pytest.mark.parametrize(
    ("admitted_by", "expected"),
    [
        ("max_wait", "sase: no check slot after max wait"),
        (
            "unavailable",
            "sase: check admission unavailable; running through the recorded bypass",
        ),
    ],
)
def test_follower_bypass_copy_names_its_reason(admitted_by: str, expected: str) -> None:
    from sase.tool.admission_display import follower_granted_line

    run = {
        "state": "running",
        "demand": {
            "admission": {
                "state": "admitted",
                "key": "check",
                "wait_ms": 90000,
                "admitted_by": admitted_by,
            }
        },
    }
    line = follower_granted_line(run)
    assert line is not None and line.startswith(expected)
    assert "slot granted" not in line


def test_stats_admission_cell() -> None:
    from sase.tool.stats_report_render import _format_admission_waits

    assert _format_admission_waits(None) == ""
    assert _format_admission_waits({}) == ""
    assert _format_admission_waits({"runs": 0, "waits": 0}) == ""
    cell = _format_admission_waits(
        {
            "runs": 10,
            "waits": 4,
            "wait_ms_total": 120000,
            "wait_ms_p50": 5000,
            "wait_ms_p95": 60000,
            "wait_ms_max": 90000,
            "forced": 1,
            "unavailable": 2,
            "abandoned": 2,
        }
    )
    assert "admission waits 4/10 runs" in cell
    assert "1 max-wait, 2 unavailable, 2 abandoned" in cell
