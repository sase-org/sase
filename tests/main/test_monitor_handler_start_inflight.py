"""Staged in-agent ``sase monitor start`` writes no kill-path markers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
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


def _start_in_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
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
    return starter_dir


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


def _staged_result() -> SimpleNamespace:
    return SimpleNamespace(
        record=SimpleNamespace(
            monitor_id="m" * 40,
            member_agent_name="acme--mon",
            tool_run_id=None,
            tool_run_joined=False,
        ),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        payload={},
        replayed=False,
    )


def test_staged_start_writes_no_kill_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful in-agent start stages without inflight or pending kill markers."""
    starter_dir = _start_in_agent(monkeypatch, tmp_path)
    spawned: list[object] = []

    monkeypatch.setattr(
        "sase.monitor.start_stage.stage_monitor", lambda request: _staged_result()
    )
    monkeypatch.setattr(
        "sase.main.monitor.start.start_monitor",
        lambda request: spawned.append(request),
    )
    assert handle_monitor_start(_start_args(tmp_path)) == 0
    assert spawned == []
    assert not (Path(starter_dir) / MONITOR_PENDING_MARKER).exists()
    assert not (Path(starter_dir) / HANDOFF_INFLIGHT_MARKER).exists()
    assert list(Path(starter_dir).glob(".sase_handoff_inflight*")) == []


def test_failed_stage_writes_no_kill_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A staged start that errors leaves no kill-path markers behind."""
    starter_dir = _start_in_agent(monkeypatch, tmp_path)

    def _boom(request):  # type: ignore[no-untyped-def]
        raise MonitorError("boom")

    monkeypatch.setattr("sase.monitor.start_stage.stage_monitor", _boom)
    monkeypatch.setattr(
        "sase.main.monitor.start.start_monitor",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not spawn on staged path")
        ),
    )
    assert handle_monitor_start(_start_args(tmp_path)) == 1
    assert not (Path(starter_dir) / HANDOFF_INFLIGHT_MARKER).exists()
    assert not (Path(starter_dir) / MONITOR_PENDING_MARKER).exists()
    assert (
        json.loads((Path(starter_dir) / "agent_meta.json").read_text(encoding="utf-8"))[
            "name"
        ]
        == "acme"
    )
