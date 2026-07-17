"""Deterministic Telemetry-tab models for ACE PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import telemetry_pane as tp
from sase.ace.tui.modals.telemetry_pane import TelemetryPane
from sase.ace.tui.modals.telemetry_pane_data import (
    _TelemetryChartData as TelemetryChartData,
    _TelemetryTileData as TelemetryTileData,
    TelemetryViewData,
    _empty_telemetry_view,
)
from sase.telemetry.render import Series, status_color

_TELEMETRY_NOW = 1_720_268_400


def _populated_telemetry_view() -> TelemetryViewData:
    timestamps = tuple(
        _TELEMETRY_NOW - offset for offset in (3_000, 2_400, 1_800, 1_200, 600, 0)
    )
    runs = (
        Series.from_pairs(
            "ok",
            tuple(zip(timestamps, (2, 4, 3, 6, 5, 8), strict=True)),
            label="ok",
            color=status_color("ok"),
        ),
        Series.from_pairs(
            "error",
            tuple(zip(timestamps, (0, 1, 0, 1, 1, 0), strict=True)),
            label="error",
            color=status_color("critical"),
        ),
    )
    durations = (
        Series.from_pairs(
            "p50",
            tuple(zip(timestamps, (42, 48, 45, 51, 47, 44), strict=True)),
            label="p50",
            color="#00D7AF",
        ),
        Series.from_pairs(
            "p95",
            tuple(zip(timestamps, (150, 170, 162, 190, 176, 168), strict=True)),
            label="p95",
            color="#AF87FF",
        ),
    )
    tokens = (
        Series.from_pairs(
            "codex",
            tuple(
                zip(
                    timestamps,
                    (12_000, 18_000, 14_000, 24_000, 21_000, 28_000),
                    strict=True,
                )
            ),
            label="codex",
            color="#87D7FF",
        ),
        Series.from_pairs(
            "claude",
            tuple(
                zip(
                    timestamps,
                    (8_000, 9_000, 13_000, 11_000, 16_000, 15_000),
                    strict=True,
                )
            ),
            label="claude",
            color="#FFD700",
        ),
    )
    errors = (
        Series.from_pairs(
            "error-rate",
            tuple(zip(timestamps, (0.0, 20.0, 0.0, 14.3, 16.7, 0.0), strict=True)),
            label="Error rate",
            color=status_color("critical"),
        ),
    )
    return TelemetryViewData(
        subsystem="agents",
        range_key="1h",
        generated_at=_TELEMETRY_NOW,
        recording_started_at=_TELEMETRY_NOW - 86_400,
        enabled=True,
        empty=False,
        store_path="~/.sase/telemetry/metrics.sqlite",
        tiles=(
            TelemetryTileData("Active Agents", 7.0, "agents"),
            TelemetryTileData("Active Workspaces", 5.0, "workspaces"),
            TelemetryTileData("Active Beads", 12.0, "beads"),
            TelemetryTileData(
                "Runs in range",
                32.0,
                "runs",
                delta=18.5,
                sparkline=(2, 5, 3, 7, 6, 8),
            ),
            TelemetryTileData(
                "Error rate",
                8.6,
                "errors",
                value_format="percent",
                delta=-3.2,
                lower_is_better=True,
                sparkline=(0.0, 20.0, 0.0, 14.3, 16.7, 0.0),
                status="ok",
            ),
        ),
        charts=(
            TelemetryChartData("Agent Runs by status", runs),
            TelemetryChartData(
                "Run Duration p50 / p95",
                durations,
                value_format="duration",
                y_label="duration",
            ),
            TelemetryChartData(
                "LLM Tokens by provider",
                tokens,
                value_format="tokens",
                y_label="tokens",
            ),
            TelemetryChartData(
                "Error Rate %",
                errors,
                value_format="percent",
                y_label="errors",
                y_min=0,
                y_max=100,
            ),
        ),
        health_status="ok",
        health_text="HEALTHY · Agents 8.6% errors · LLM 2.1% errors · Axe 0 errors",
    )


def _patch_telemetry_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tp, "load_telemetry_view", lambda *_args: _populated_telemetry_view()
    )


def _patch_telemetry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tp,
        "load_telemetry_view",
        lambda subsystem, range_key: _empty_telemetry_view(
            subsystem,
            range_key,
            generated_at=_TELEMETRY_NOW,
            store_path="~/.sase/telemetry/metrics.sqlite",
        ),
    )


def _patch_telemetry_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    def stay_loading(self: TelemetryPane) -> None:
        self._loading = True
        self._update_heading()
        self._paint_loading()

    monkeypatch.setattr(TelemetryPane, "_start_load", stay_loading)


__all__ = [
    "_patch_telemetry_empty",
    "_patch_telemetry_loading",
    "_patch_telemetry_populated",
]
