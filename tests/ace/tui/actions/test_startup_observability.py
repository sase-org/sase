"""Startup observability added for sase-132.1.

Sub-stage loader spans, axe first-load spans with file_opens, and the
startup-window marker on spans emitted before the stopwatch ends.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    collect_axe_status_data,
)
from sase.ace.tui.actions.axe_display._loader_refresh import (
    AxeDisplayRefreshMixin,
)
from sase.ace.tui.actions.axe_display._read_cache import AxeCollectorStats
from sase.ace.tui.data_providers import AgentsProviderSnapshot
from sase.ace.tui.data_providers._snapshots import agent_snapshot
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import (
    AgentLoadState,
    _load_agents_with_load_state,
)
from sase.ace.tui.util import trace
from sase.core.agent_scan_wire import AgentArtifactScanWire
from tests._agent_loader_helpers import _empty_artifact_snapshot
from tests.ace.tui._axe_collector_helpers import patch_service_status


def _records(path: Path) -> list[dict[str, Any]]:
    trace._flush_trace_writes()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _enable_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._flush_trace_writes()
    trace._context.clear()
    trace.set_startup_window(False)
    return log


def _make_agent() -> Agent:
    from datetime import datetime

    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sample-cl",
        project_file="/tmp/myproj/myproj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 6, 12, 0, 0),
    )


def _provider_snapshot(
    agent: Agent, load_state: AgentLoadState
) -> AgentsProviderSnapshot:
    return AgentsProviderSnapshot(
        agents=[agent],
        workflow_agent_steps=[],
        load_state=load_state,
        shared_snapshot=agent_snapshot(
            [agent],
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id="snap-1",
            page_count=1,
            full_reload=True,
        ),
    )


def test_load_from_disk_emits_substage_spans_under_slow_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake slow provider still emits provider + projections substages."""
    log = _enable_trace(tmp_path, monkeypatch)
    trace.set_startup_window(True)
    agent = _make_agent()
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=96,
        returned_count=1,
    )
    snapshot = _provider_snapshot(agent, load_state)

    class SlowProvider:
        prefers_daemon = False

        def load_agents(self, **kwargs: object) -> AgentsProviderSnapshot:
            time.sleep(0.05)  # sase-test-wait: fake slow provider for span duration
            return snapshot

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_bundle_identities_snapshot",
            return_value=set(),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        load_agents_from_disk_with_state(
            set(), source="startup", data_provider=SlowProvider()
        )

    rows = _records(log)
    by_span = {row["span"]: row for row in rows if "span" in row}
    assert "agents.load_from_disk" in by_span
    assert "agents.load_from_disk.dismissed_snapshot" in by_span
    assert "agents.load_from_disk.provider" in by_span
    assert "agents.load_from_disk.projections" in by_span
    assert by_span["agents.load_from_disk.provider"]["duration_ms"] >= 40.0
    assert by_span["agents.load_from_disk"]["source"] == "startup"
    for span in (
        "agents.load_from_disk",
        "agents.load_from_disk.dismissed_snapshot",
        "agents.load_from_disk.provider",
        "agents.load_from_disk.projections",
    ):
        assert by_span[span]["startup_window"] is True


def test_load_state_emits_index_and_decode_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Rust index read and row decode are separate nested spans."""
    log = _enable_trace(tmp_path, monkeypatch)
    agent = _make_agent()
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        record_count=12,
    )
    snapshot = _empty_artifact_snapshot()

    def _slow_index(**kwargs: object) -> tuple[AgentArtifactScanWire, AgentLoadState]:
        time.sleep(0.02)  # sase-test-wait: fake slow index for span duration
        return snapshot, load_state

    def _slow_decode(**kwargs: object) -> tuple[list[Agent], list[Agent]]:
        time.sleep(0.03)  # sase-test-wait: fake slow decode for span duration
        return [agent], []

    with (
        patch(
            "sase.ace.tui.models.agent_loader._artifact_snapshot_for_tui_load",
            side_effect=_slow_index,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._load_agents_from_all_sources",
            side_effect=_slow_decode,
        ),
    ):
        _load_agents_with_load_state()

    rows = _records(log)
    by_span = {row["span"]: row for row in rows if "span" in row}
    assert by_span["agents.load_from_disk.index"]["artifact_source"] == (
        "artifact_index"
    )
    assert by_span["agents.load_from_disk.index"]["record_count"] == 12
    assert by_span["agents.load_from_disk.index"]["duration_ms"] >= 15.0
    assert by_span["agents.load_from_disk.decode"]["decoded_count"] == 1
    assert by_span["agents.load_from_disk.decode"]["duration_ms"] >= 25.0


def test_axe_collect_span_carries_file_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """axe.collect is a duration span with file_opens, plus the legacy event."""
    log = _enable_trace(tmp_path, monkeypatch)
    trace.set_startup_window(True)

    with (
        patch_service_status(),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_output_log_tail",
            return_value="",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
        patch(
            "sase.axe.config.load_axe_config",
            return_value=type("Cfg", (), {"lumberjacks": {}})(),
        ),
    ):
        collect_axe_status_data(include_full_snapshots=False)

    rows = _records(log)
    span_rows = [row for row in rows if row.get("span") == "axe.collect"]
    event_rows = [row for row in rows if row.get("event") == "axe.collect"]
    assert len(span_rows) == 1
    assert len(event_rows) == 1
    assert "file_opens" in span_rows[0]
    assert span_rows[0]["startup_window"] is True
    assert event_rows[0]["startup_window"] is True
    assert isinstance(span_rows[0]["duration_ms"], (int, float))


class _AxeStartupHarness(AxeDisplayRefreshMixin):
    def __init__(self, *, current_tab: str = "agents") -> None:
        self._axe_first_load_done = False
        self.current_tab = current_tab
        self._startup_initial_tab = current_tab
        self._restart_axe = False
        self._auto_start_axe = False
        self.axe_running = False
        self.applied: AxeCollectedData | None = None
        self.collect_kwargs: list[dict[str, object]] = []
        self.scheduled_full_refresh = 0

    def _apply_axe_status_data(self, data: AxeCollectedData) -> None:
        self.applied = data

    def _schedule_axe_async_refresh(self) -> None:
        self.scheduled_full_refresh += 1


@pytest.mark.asyncio
async def test_axe_startup_path_emits_startup_and_load_status_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_axe_startup_init emits axe.startup and axe.load_status with file_opens."""
    log = _enable_trace(tmp_path, monkeypatch)
    trace.set_startup_window(True)
    stats = AxeCollectorStats(file_opens=7, run_json_parses=2)
    payload = AxeCollectedData(
        axe_running=False,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=[],
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=False,
        stats=stats,
    )

    def _slow_collect(**kwargs: object) -> AxeCollectedData:
        app.collect_kwargs.append(dict(kwargs))
        time.sleep(0.03)  # sase-test-wait: fake slow axe collect for span duration
        return payload

    app = _AxeStartupHarness()
    monkeypatch.setattr(
        "sase.ace.tui.actions.axe_display._loader_refresh.collect_axe_status_data",
        _slow_collect,
    )
    await app._run_axe_startup_init()

    rows = _records(log)
    by_span = {row["span"]: row for row in rows if "span" in row}
    assert "axe.startup" in by_span
    assert "axe.load_status" in by_span
    assert by_span["axe.load_status"]["file_opens"] == 7
    assert by_span["axe.load_status"]["include_full_snapshots"] is False
    assert by_span["axe.load_status"]["duration_ms"] >= 20.0
    assert by_span["axe.startup"]["startup_window"] is True
    assert by_span["axe.load_status"]["startup_window"] is True
    assert app.applied is payload
    assert app.collect_kwargs[0]["include_full_snapshots"] is False
    assert app.scheduled_full_refresh == 0


@pytest.mark.asyncio
async def test_axe_startup_on_axe_tab_schedules_background_full_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Visible AXE tab still paints cheaply, then coalesces a full follow-up."""
    _enable_trace(tmp_path, monkeypatch)
    stats = AxeCollectorStats(file_opens=0, run_json_parses=0)
    payload = AxeCollectedData(
        axe_running=False,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=["hooks"],
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={"hooks": ["fast"]},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=False,
        stats=stats,
    )
    collect_kwargs: list[dict[str, object]] = []

    def _collect(**kwargs: object) -> AxeCollectedData:
        collect_kwargs.append(dict(kwargs))
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.actions.axe_display._loader_refresh.collect_axe_status_data",
        _collect,
    )
    app = _AxeStartupHarness(current_tab="axe")
    await app._run_axe_startup_init()

    assert collect_kwargs[0]["include_full_snapshots"] is False
    assert app.scheduled_full_refresh == 1
    assert app.applied is payload
