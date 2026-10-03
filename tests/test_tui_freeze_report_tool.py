"""Tests for the `tools/tui_freeze_report` CLI wrapper.

The report is driven against synthetic JSONL fixtures that mix pre-phase
rows (no ``app_instance_id``, no additive fields) with current rows, so old
logs keep reporting instead of breaking the acceptance tool.
"""

from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "tui_freeze_report"


def _load_tool() -> ModuleType:
    loader = SourceFileLoader("tui_freeze_report_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "tui_freeze_report_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tool() -> ModuleType:
    return _load_tool()


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def stalls_path(tmp_path: Path) -> Path:
    return _write_jsonl(
        tmp_path / "tui_stalls.jsonl",
        [
            # Old rows: no instance ID, no additive fields.
            {"ts": 600.0, "event": "tui_hitch", "pid": 11, "stall_seconds": 1.6},
            {
                "ts": 601.6,
                "event": "tui_hitch_recovered",
                "pid": 11,
                "duration_seconds": 1.6,
            },
            # Current rows for instance "aaa".
            {
                "ts": 1000.0,
                "event": "tui_hitch",
                "pid": 12,
                "stall_seconds": 2.0,
                "late": True,
                "poll_lag_s": 1.9,
                "net_stall_seconds": 1.9,
                "detected_by": "watchdog_lateness",
                "app_instance_id": "aaa",
                "last_keypress_age_s": 0.5,
            },
            {
                "ts": 1002.0,
                "event": "tui_hitch_recovered",
                "pid": 12,
                "duration_seconds": 2.0,
                "late": True,
                "gc_overlap_s": 1.8,
                "gc_generations": [2],
                "gc_triggers": ["automatic"],
                "app_instance_id": "aaa",
            },
            {
                "ts": 1001.0,
                "event": "tui_gc_pause",
                "pid": 12,
                "generation": 2,
                "duration_s": 1.8,
                "trigger": "automatic",
                "app_instance_id": "aaa",
            },
            {
                "ts": 1005.0,
                "event": "tui_gc_pause",
                "pid": 12,
                "generation": 2,
                "duration_s": 0.4,
                "trigger": "idle",
                "app_instance_id": "aaa",
            },
            # Pump-tier rows never enter the loop-only frozen union.
            {
                "ts": 1020.0,
                "event": "tui_pump_hitch",
                "pid": 12,
                "stall_seconds": 5.0,
                "app_instance_id": "aaa",
            },
            {
                "ts": 1010.0,
                "event": "tui_memory_heartbeat",
                "pid": 12,
                "app_instance_id": "aaa",
                "rss_bytes": 100 * 1024 * 1024,
                "vmswap_bytes": 0,
                "gc_generations": {"2": {"count": 1, "total_s": 1.8, "max_s": 1.8}},
                "loop_hitch_episodes": 1,
                "loop_hitch_seconds": 2.0,
            },
            "not-json{{{",
        ],
    )


@pytest.fixture
def startup_path(tmp_path: Path) -> Path:
    return _write_jsonl(
        tmp_path / "tui_startup.jsonl",
        [{"ts": 500.0, "event": "tui_startup", "pid": 11}],
    )


def test_old_rows_bucket_into_startup_windows(
    tool: ModuleType, stalls_path: Path, startup_path: Path
) -> None:
    rows = tool.load_rows(stalls_path)
    assert len(rows) == 8  # the corrupt line is skipped
    startups = tool.load_rows(startup_path)
    buckets = tool.bucket_by_instance(rows, startups)
    assert sorted(buckets) == ["aaa", "startup-0"]
    assert len(buckets["aaa"]) == 6
    assert len(buckets["startup-0"]) == 2


def test_instance_summary_reports_frozen_and_gc_share(
    tool: ModuleType, stalls_path: Path, startup_path: Path
) -> None:
    buckets = tool.bucket_by_instance(
        tool.load_rows(stalls_path), tool.load_rows(startup_path)
    )
    summary = tool.summarize_instance(buckets["aaa"], since=1000.0, until=1030.0)
    assert summary["episodes"] == 1
    assert summary["frozen_s"] == pytest.approx(2.0)
    assert summary["frozen_share"] == pytest.approx(2.0 / 30.0)
    assert summary["late_episodes"] == 1
    assert summary["ontime_episodes"] == 0
    assert summary["gc_total_s"] == pytest.approx(1.8)
    assert summary["gc_share"] == pytest.approx(1.8 / 30.0)
    assert summary["gc_seconds_by_generation"] == {"2": 1.8}
    assert summary["gc_seconds_by_gen_trigger"] == {
        "gen-2/automatic": 1.8,
        "gen-2/idle": 0.4,
    }
    assert summary["idle_pause_count"] == 1
    assert summary["idle_pause_p50"] == pytest.approx(0.4)
    # The automatic gen-2 pause sits 1 s from a hitch row whose keypress age
    # is 0.5 s, so it counts as near input.
    assert summary["auto_gen2_total"] == 1
    assert summary["auto_gen2_near_input"] == 1
    assert summary["rss_first_bytes"] == 100 * 1024 * 1024


def test_old_rows_report_without_additive_fields(
    tool: ModuleType, stalls_path: Path, startup_path: Path
) -> None:
    buckets = tool.bucket_by_instance(
        tool.load_rows(stalls_path), tool.load_rows(startup_path)
    )
    summary = tool.summarize_instance(buckets["startup-0"], since=500.0, until=700.0)
    assert summary["episodes"] == 1
    assert summary["frozen_s"] == pytest.approx(1.6)
    assert summary["ontime_episodes"] == 1
    assert summary["late_episodes"] == 0
    assert summary["gc_total_s"] == pytest.approx(0.0)


def test_main_reports_selected_instance(
    tool: ModuleType,
    stalls_path: Path,
    startup_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        tool.main(
            [
                "--path",
                str(stalls_path),
                "--startup-path",
                str(startup_path),
                "--since",
                "1000",
                "--until",
                "1030",
                "--instance",
                "aaa",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "instance aaa" in out
    assert "startup-0" not in out
    assert "6.67%" in out  # 2 s frozen of a 30 s window


def test_main_empty_window_reports_no_rows(
    tool: ModuleType,
    stalls_path: Path,
    startup_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        tool.main(
            [
                "--path",
                str(stalls_path),
                "--startup-path",
                str(startup_path),
                "--since",
                "2000",
                "--until",
                "2010",
            ]
        )
        == 0
    )
    assert "no rows" in capsys.readouterr().out
