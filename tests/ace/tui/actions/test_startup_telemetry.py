"""Tests for the durable one-record-per-session ACE startup telemetry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions._startup_telemetry import StartupTelemetryMixin
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.logs import tui_telemetry


class _TelemetryApp(StartupTelemetryMixin):
    def __init__(self, *, current_tab: str = "agents") -> None:
        self.current_tab = current_tab
        self._startup_process_start_mono = 100.0
        self._startup_on_mount_mono: float | None = None
        self._startup_first_paint_mono: float | None = None
        self._startup_initial_tab: str | None = None
        self._startup_agents_ready_mono: float | None = None
        self._startup_axe_ready_mono: float | None = None
        self._startup_visible_ready_mono: float | None = None
        self._startup_telemetry_recorded = False
        self._startup_telemetry_async_tasks: set[asyncio.Task[None]] = set()
        self._agents_first_load_done = False
        self._axe_first_load_done = False
        self._agents: list[Any] = []
        self._agents_refresh_active_source = "startup"
        self._agent_load_state: AgentLoadState | None = None


async def _drain(app: _TelemetryApp) -> None:
    for _ in range(200):
        tasks = tuple(app._startup_telemetry_async_tasks)
        if not tasks:
            return
        await asyncio.gather(*tasks)
    raise AssertionError("startup telemetry task did not drain")


def test_visible_surface_ready_matches_initial_tab() -> None:
    app = _TelemetryApp(current_tab="agents")
    app._startup_initial_tab = "agents"
    assert not app._startup_visible_surface_ready()
    app._agents_first_load_done = True
    assert app._startup_visible_surface_ready()

    axe_app = _TelemetryApp(current_tab="axe")
    axe_app._startup_initial_tab = "axe"
    assert not axe_app._startup_visible_surface_ready()
    axe_app._axe_first_load_done = True
    assert axe_app._startup_visible_surface_ready()

    artifacts_app = _TelemetryApp(current_tab="artifacts")
    artifacts_app._startup_initial_tab = "artifacts"
    assert artifacts_app._startup_visible_surface_ready()


def test_mark_startup_on_mount_snapshots_tab_once() -> None:
    app = _TelemetryApp(current_tab="axe")
    app._mark_startup_on_mount()
    first_mono = app._startup_on_mount_mono
    assert app._startup_initial_tab == "axe"
    assert first_mono is not None

    app.current_tab = "agents"
    app._mark_startup_on_mount()
    assert app._startup_on_mount_mono == first_mono
    assert app._startup_initial_tab == "axe"


@pytest.mark.asyncio
async def test_record_waits_for_both_surfaces_then_writes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_startup.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STARTUP_JSONL", str(path))

    app = _TelemetryApp(current_tab="agents")
    app._mark_startup_on_mount()
    app._mark_startup_first_paint()
    app._agents = [object(), object(), object()]
    app._agent_load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        record_count=7,
    )

    app._agents_first_load_done = True
    app._mark_startup_agents_ready()
    await _drain(app)
    assert not path.exists()  # axe surface is not ready yet

    app._axe_first_load_done = True
    app._mark_startup_axe_ready()
    await _drain(app)

    record = json.loads(path.read_text().strip())
    assert record["event"] == "tui_startup"
    assert record["initial_tab"] == "agents"
    assert record["source"] == "startup"
    assert record["tier"] == "tier1"
    assert record["artifact_source"] == "artifact_index"
    assert record["agent_row_count"] == 3
    assert record["index_row_count"] == 7
    assert record["all_surfaces_ready_seconds"] >= 0
    assert record["visible_ready_seconds"] >= 0
    assert record["process_start_to_on_mount_seconds"] >= 0
    assert record["on_mount_to_first_paint_seconds"] >= 0
    assert record["agents_ready_seconds"] >= 0
    assert record["axe_ready_seconds"] >= 0

    # A repeat "ready" signal (e.g. a redundant call) must not write again.
    app._mark_startup_agents_ready()
    app._mark_startup_axe_ready()
    await _drain(app)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
