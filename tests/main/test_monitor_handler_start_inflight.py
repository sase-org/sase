"""In-flight marker lifecycle for in-agent ``sase monitor start``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.handoff_inflight import (
    HANDOFF_INFLIGHT_MARKER,
    _read_handoff_inflight_marker,
)
from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.main.monitor.start import handle_monitor_start
from sase.monitor import MonitorError
from sase.running_field import WorkspaceClaim
from tests.main.monitor_handler_helpers import (
    monitor_home,
    pin_project,
)
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
    """Build a starter agent and pin this process inside it."""
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


def test_inflight_marker_written_before_start_and_superseded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The marker exists during the slow start and is gone after handoff."""
    starter_dir, kills = _start_in_agent(monkeypatch, tmp_path)
    observed: dict = {}

    def _fake_start(request):  # type: ignore[no-untyped-def]
        observed["inflight"] = _read_handoff_inflight_marker(starter_dir)
        return SimpleNamespace(
            monitor_id="m" * 40,
            member_agent_name="acme--mon",
            artifacts_dir=str(tmp_path / "member"),
            lane="acme",
            project_name="proj",
            command=request.command,
            cwd=request.cwd,
            next_action=request.next_action,
            next_model=None,
            next_output=request.next_output,
            request_fingerprint="fp",
            tool_run_id=None,
        )

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", _fake_start)
    assert handle_monitor_start(_start_args(tmp_path)) == 0

    marker = observed.get("inflight")
    assert marker is not None
    assert marker["lane"] == "acme"
    assert marker["pid"] == os.getpid()
    assert (Path(starter_dir) / MONITOR_PENDING_MARKER).is_file()
    assert not (Path(starter_dir) / HANDOFF_INFLIGHT_MARKER).exists()
    assert kills == [starter_dir]


def test_failed_start_removes_inflight_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A start that errors after the marker write leaves no marker behind."""
    starter_dir, kills = _start_in_agent(monkeypatch, tmp_path)

    def _boom(request):  # type: ignore[no-untyped-def]
        raise MonitorError("boom")

    monkeypatch.setattr("sase.main.monitor.start.start_monitor", _boom)
    assert handle_monitor_start(_start_args(tmp_path)) == 1
    assert not (Path(starter_dir) / HANDOFF_INFLIGHT_MARKER).exists()
    assert not (Path(starter_dir) / MONITOR_PENDING_MARKER).exists()
    assert kills == []
    assert (
        json.loads((Path(starter_dir) / "agent_meta.json").read_text(encoding="utf-8"))[
            "name"
        ]
        == "acme"
    )
