"""Worker, coalescing, and query-model coverage for the Telemetry tab."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sase_core_rs import telemetry_record_batch

from sase.ace.testing import AcePage
from sase.ace.tui.modals import telemetry_pane as tp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.telemetry_pane import TelemetryPane
from sase.ace.tui.modals.telemetry_pane_data import (
    SUBSYSTEM_ORDER,
    _TelemetryChartData as TelemetryChartData,
    TelemetryRange,
    TelemetrySubsystem,
    _TelemetryTileData as TelemetryTileData,
    TelemetryViewData,
    load_telemetry_view,
)
from sase.telemetry._config import _TelemetryConfig
from sase.telemetry.render import Series

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)

_NOW = 1_700_000_000


def _view(
    subsystem: TelemetrySubsystem,
    range_key: TelemetryRange,
) -> TelemetryViewData:
    points = ((_NOW - 120, 2.0), (_NOW - 60, 4.0), (_NOW, 3.0))
    series = (Series.from_pairs("ok", points, label="ok"),)
    return TelemetryViewData(
        subsystem=subsystem,
        range_key=range_key,
        generated_at=_NOW,
        recording_started_at=_NOW - 3_600,
        enabled=True,
        empty=False,
        store_path="/tmp/telemetry.sqlite",
        tiles=(
            TelemetryTileData("Active Agents", 3.0, "agents"),
            TelemetryTileData("Active Workspaces", 2.0, "workspaces"),
            TelemetryTileData("Active Beads", 4.0, "beads"),
            TelemetryTileData("Runs in range", 9.0, "runs", sparkline=(2.0, 4.0, 3.0)),
            TelemetryTileData(
                "Error rate",
                2.5,
                "errors",
                value_format="percent",
                status="ok",
            ),
        ),
        charts=tuple(
            TelemetryChartData(f"Chart {index}", series) for index in range(1, 5)
        ),
        health_status="ok",
        health_text="HEALTHY · Agents 2.5% errors",
    )


def _patch_center(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[TelemetrySubsystem, TelemetryRange]],
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    def load(
        subsystem: TelemetrySubsystem,
        range_key: TelemetryRange,
    ) -> TelemetryViewData:
        calls.append((subsystem, range_key))
        return _view(subsystem, range_key)

    monkeypatch.setattr(tp, "load_telemetry_view", load)


async def _open_telemetry(page: AcePage) -> tuple[ConfigCenterModal, TelemetryPane]:
    modal = ConfigCenterModal(initial_tab="telemetry")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _state: bool(modal.query("#telemetry")))
    pane = modal.query_one("#telemetry", TelemetryPane)
    await page.wait_for(lambda _state: not pane._loading and pane._loaded_once)
    return modal, pane


async def test_telemetry_loads_only_after_its_tab_becomes_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[TelemetrySubsystem, TelemetryRange]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: bool(modal.query("#telemetry")))
        pane = modal.query_one("#telemetry", TelemetryPane)
        await page.pause()

        assert calls == []
        assert pane._worker is None

        await page.press("5")
        await page.wait_for(lambda _state: pane._loaded_once and not pane._loading)

        assert calls == [("agents", "1h")]
        assert pane._last_result is not None
        assert pane._last_result.subsystem == "agents"


async def test_range_and_subsystem_switches_coalesce_to_latest_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[TelemetrySubsystem, TelemetryRange]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_telemetry(page)
        # Invoke the actions in one event-loop turn so this specifically
        # exercises rapid selection coalescing. Pilot key presses deliberately
        # pause between events and can exceed the debounce window under xdist.
        pane.action_cycle_subsystem()
        pane.action_cycle_subsystem()
        pane.action_cycle_range()
        pane.action_cycle_range()
        await page.wait_for(
            lambda _state: (
                pane._load_debouncer is not None
                and not pane._load_debouncer.is_pending
                and not pane._loading
                and pane._last_result is not None
                and pane._last_result.subsystem == "axe"
                and pane._last_result.range_key == "24h"
            )
        )

        assert calls == [("agents", "1h"), ("axe", "24h")]
        assert pane._subsystem == "axe"
        assert pane._range_key == "24h"


async def test_refresh_preserves_selection_and_hidden_tick_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[TelemetrySubsystem, TelemetryRange]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_telemetry(page)
        await page.press("s", "t")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.subsystem == "llm"
                and pane._last_result.range_key == "6h"
            )
        )
        await page.press("r")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)

        assert calls[-1] == ("llm", "6h")
        modal._switch_to("config")
        pane._on_refresh_tick()
        await page.pause()
        assert calls[-1] == ("llm", "6h")
        assert pane._load_debouncer is not None
        assert not pane._load_debouncer.is_pending


def test_local_store_models_agent_tiles_and_all_subsystem_chart_sets(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "metrics.sqlite"
    config = _TelemetryConfig(enabled=True, store_path=store_path)
    samples = [
        {
            "ts": _NOW,
            "metric": "sase_agent_runs_total",
            "kind": "counter",
            "labels": {"llm_provider": "codex", "status": "ok", "workflow": "run"},
            "source": "test:pid=1",
            "value": 4.0,
        },
        {
            "ts": _NOW,
            "metric": "sase_agent_runs_total",
            "kind": "counter",
            "labels": {
                "llm_provider": "codex",
                "status": "error",
                "workflow": "run",
            },
            "source": "test:pid=1",
            "value": 1.0,
        },
        {
            "ts": _NOW,
            "metric": "sase_agent_active",
            "kind": "gauge",
            "labels": {"llm_provider": "codex", "project": "sase"},
            "source": "test:pid=1",
            "value": 2.0,
        },
        {
            "ts": _NOW,
            "metric": "sase_agent_run_duration_seconds",
            "kind": "histogram",
            "labels": {"llm_provider": "codex", "workflow": "run"},
            "source": "test:pid=1",
            "count": 2,
            "sum": 130.0,
            "min": 10.0,
            "max": 120.0,
            "buckets": [{"le": 10.0, "count": 1}, {"le": 120.0, "count": 2}],
        },
    ]
    telemetry_record_batch(
        str(store_path),
        {
            "samples": samples,
            "now_ts": _NOW,
            "retention": config.retention.as_wire(),
        },
    )

    with patch("sase.telemetry._config.get_telemetry_config", return_value=config):
        agents = load_telemetry_view("agents", "1h", now_ts=_NOW)
        views = [
            load_telemetry_view(subsystem, "1h", now_ts=_NOW)
            for subsystem in SUBSYSTEM_ORDER
        ]

    assert agents.empty is False
    assert [tile.value for tile in agents.tiles] == [2.0, 0.0, 0.0, 5.0, 20.0]
    assert agents.health_status == "warning"
    assert len(agents.charts) == 4
    assert all(len(view.charts) == 4 for view in views)
