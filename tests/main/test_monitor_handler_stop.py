"""Behavior tests for the ``sase monitor stop`` handler."""

from __future__ import annotations

import json
import os
import signal
import subprocess

import pytest

from tests.main.monitor_handler_helpers import (
    dispatch,
    make_monitor,
    monitor_home,
    patch_project_records,
)

__all__ = ["monitor_home"]


def test_stop_signals_the_supervisor_and_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stopping a running monitor signals its supervisor pid and confirms it."""
    child = subprocess.Popen(["sleep", "30"])
    real_kill = os.kill
    signaled: list[int] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            real_kill(pid, sig)
            return
        assert pid == child.pid
        assert sig == signal.SIGTERM
        signaled.append(pid)
        _set_monitor_state(artifacts_dir, "stopped")

    try:
        artifacts_dir = make_monitor(
            "proj",
            "20260812120000",
            "acme--mon",
            lane="acme",
            monitor_id="aaabbbcccddd",
            pid=child.pid,
        )
        patch_project_records(monkeypatch, [artifacts_dir])
        monkeypatch.setattr("os.kill", fake_kill)

        assert dispatch(["monitor", "stop", "aaabbbcccddd"]) == 0

        assert signaled == [child.pid]
        out = capsys.readouterr().out
        assert "Stopped monitor aaabbb" in out
    finally:
        if child.poll() is None:
            real_kill(child.pid, signal.SIGKILL)
        child.wait()


def test_stop_already_terminal_reports_nothing_to_do(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finished monitor reports it is already done instead of erroring."""
    artifacts_dir = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
    )
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "stop", "aaabbbcccddd"]) == 0

    out = capsys.readouterr().out
    assert "already completed; nothing to do" in out


def test_stop_omitted_id_targets_the_calling_agents_active_monitor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No id, but a resolvable agent, stops that agent's active monitor."""
    child = subprocess.Popen(["sleep", "30"])
    real_kill = os.kill

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            real_kill(pid, sig)
            return
        _set_monitor_state(artifacts_dir, "stopped")

    try:
        artifacts_dir = make_monitor(
            "proj",
            "20260812120000",
            "acme--mon",
            lane="acme",
            monitor_id="aaabbbcccddd",
            pid=child.pid,
        )
        patch_project_records(monkeypatch, [artifacts_dir])
        monkeypatch.setattr("os.kill", fake_kill)
        monkeypatch.setattr("sase.main.monitor_handler.default_lane", lambda: "acme")
        monkeypatch.setattr(
            "sase.main.monitor_handler._infer_project_name", lambda _cwd: "proj"
        )

        assert dispatch(["monitor", "stop"]) == 0

        out = capsys.readouterr().out
        assert "Stopped monitor aaabbb" in out
    finally:
        if child.poll() is None:
            real_kill(child.pid, signal.SIGKILL)
        child.wait()


def test_stop_omitted_id_without_an_agent_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no id and no resolvable agent, ``stop`` reports a usage error."""
    assert dispatch(["monitor", "stop"]) == 2
    assert "SASE_AGENT_NAME is unset" in capsys.readouterr().err


def test_stop_omitted_id_with_no_active_monitor_names_the_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A resolvable agent with no active monitor is reported by agent name."""
    patch_project_records(monkeypatch, [])
    monkeypatch.setattr("sase.main.monitor_handler.default_lane", lambda: "acme")
    monkeypatch.setattr(
        "sase.main.monitor_handler._infer_project_name", lambda _cwd: "proj"
    )

    assert dispatch(["monitor", "stop"]) == 2
    assert "agent 'acme' has no active monitor" in capsys.readouterr().err


def test_stop_json_envelope_is_stable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--json`` reports ``changed`` and the monitor projection."""
    artifacts_dir = make_monitor(
        "proj",
        "20260812120000",
        "acme--mon",
        lane="acme",
        monitor_id="aaabbbcccddd",
        monitor_state="completed",
        exit_code=0,
    )
    patch_project_records(monkeypatch, [artifacts_dir])

    assert dispatch(["monitor", "stop", "aaabbbcccddd", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["changed"] is False
    assert payload["monitor"]["monitor_id"] == "aaabbbcccddd"


def _set_monitor_state(artifacts_dir: str, state: str) -> None:
    from pathlib import Path

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_state"] = state
    meta["monitor_settled"] = state != "running"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
