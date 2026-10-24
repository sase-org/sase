"""Perf-input and workload analysis for the freeze report (sase-1nf.14.1.2)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_perf_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "tools" / "_tui_freeze_report_perf.py"
    loader = importlib.util.spec_from_file_location("_tui_freeze_report_perf", path)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


perf = _load_perf_module()

INSTANCE = "aaa"
OTHER = "bbb"
COVERAGE_START = 0.0
COVERAGE_END = 20_000.0
BUSY_SINCE = 5_000.0
BUSY_UNTIL = 8_600.0


def _sample(
    action: str,
    tab: str,
    wall: float,
    *,
    instance: str = INSTANCE,
    paint_ms: float = 5.0,
    pid: int = 100,
) -> dict:
    row: dict = {
        "action": action,
        "tab": tab,
        "t_keypress": 1.0,
        "t_wall": wall,
        "model_ms": 1.0,
        "paint_ms": paint_ms,
    }
    if instance != "LEGACY":
        row["app_instance_id"] = instance
    row["pid"] = pid
    return row


def _activity(
    transition: str,
    state: str,
    wall: float,
    *,
    instance: str = INSTANCE,
    screen: str | None = None,
    text_entry: bool | None = None,
) -> dict:
    return {
        "event": "prompt_activity",
        "transition": transition,
        "state": state,
        "screen": screen,
        "text_entry": text_entry,
        "app_instance_id": instance,
        "pid": 100,
        "t_mono": wall,
        "t_wall": wall,
    }


def _busy_agents_floor() -> list[dict]:
    """100 Agents next/prev samples across four ten-minute bins, p95 < 16ms."""
    rows: list[dict] = []
    for index in range(100):
        wall = BUSY_SINCE + (index % 4) * 600.0 + (index // 4)
        rows.append(_sample("next" if index % 2 else "prev", "agents", wall))
    return rows


def _analyze(rows: list[dict], activity: list[dict] | None = None, **kwargs) -> dict:
    params = {
        "busy_since": BUSY_SINCE,
        "busy_until": BUSY_UNTIL,
        "required_tabs": (),
        "coverage_start": COVERAGE_START,
        "coverage_end": COVERAGE_END,
        "activity_rows": activity if activity is not None else [],
    }
    params.update(kwargs)
    return perf.analyze_instance_perf(rows, INSTANCE, **params)


def test_action_filtering_separates_nav_from_leader_prompt_panel() -> None:
    rows = [
        _sample("next", "agents", BUSY_SINCE + 1),
        _sample("files.prev", "artifacts", BUSY_SINCE + 2),
        _sample(",j", "agents", BUSY_SINCE + 3),
        _sample("prompt_space", "agents", BUSY_SINCE + 4),
        _sample("next_agent_panel", "agents", BUSY_SINCE + 5),
        _sample("agents_tab_switch", "agents", BUSY_SINCE + 6),
        _sample("mystery", "agents", BUSY_SINCE + 7),
    ]
    result = _analyze(rows)
    by_tab = result["by_tab"]
    assert set(by_tab["agents"]) == {"jk", "leader", "prompt", "panel", "other"}
    assert by_tab["agents"]["jk"]["n"] == 1
    assert by_tab["artifacts"]["jk"]["n"] == 1
    assert by_tab["agents"]["leader"]["n"] == 1
    assert by_tab["agents"]["prompt"]["n"] == 1
    assert by_tab["agents"]["panel"]["n"] == 2
    assert by_tab["agents"]["other"]["n"] == 1


def test_two_simultaneous_instances_stay_separate() -> None:
    rows = [
        _sample("next", "agents", BUSY_SINCE + 1, instance=INSTANCE),
        _sample("next", "agents", BUSY_SINCE + 1, instance=OTHER),
    ]
    result = _analyze(rows)
    assert result["attribution"]["attributed_samples"] == 1
    assert result["attribution"]["foreign_instance_rows"] == 1


def test_restart_pid_reuse_splits_on_instance_id() -> None:
    rows = [
        _sample("next", "agents", BUSY_SINCE + 1, instance=INSTANCE, pid=100),
        _sample("next", "agents", BUSY_SINCE + 2, instance=OTHER, pid=100),
    ]
    result = _analyze(rows)
    assert result["attribution"]["attributed_samples"] == 1


def test_legacy_rows_are_unattributed_and_block_pass() -> None:
    rows = [_sample("next", "agents", BUSY_SINCE + 1, instance="LEGACY")]
    result = _analyze(rows)
    assert result["attribution"]["legacy_unattributed_rows"] == 1
    assert result["attribution"]["attributed_samples"] == 0
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"
    assert any("never assigned" in issue for issue in result["issues"])


def test_valid_busy_hour_passes_with_sampling_floor() -> None:
    rows = _busy_agents_floor()
    activity = [_activity("initial", "prompt_idle", COVERAGE_START)]
    result = _analyze(rows, activity)
    assert result["targets"]["jk_p95"]["status"] == "PASS"
    assert result["targets"]["busy_hour"]["status"] == "PASS"
    assert result["targets"]["prompt_activity"]["status"] == "PASS"
    assert result["overall_status"] == "PASS"
    assert result["busy"]["tabs"]["agents"]["bins_hit"] == 4


def test_thin_busy_hour_is_incomplete() -> None:
    rows = [_sample("next", "agents", BUSY_SINCE + 1)]
    result = _analyze(rows)
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"
    assert result["targets"]["busy_hour"]["status"] == "INCOMPLETE"
    assert result["overall_status"] == "INCOMPLETE"


def test_slow_busy_hour_fails() -> None:
    rows = [
        _sample("next", "agents", BUSY_SINCE + (index % 4) * 600.0, paint_ms=20.0)
        for index in range(100)
    ]
    result = _analyze(rows)
    assert result["targets"]["jk_p95"]["status"] == "FAIL"
    assert result["targets"]["jk_p95"]["value"]["agents_p95_ms"] == pytest.approx(20.0)


def test_omitted_busy_window_reports_candidates() -> None:
    rows = _busy_agents_floor()
    result = _analyze(rows, busy_since=None, busy_until=None)
    assert result["targets"]["busy_hour"]["status"] == "INCOMPLETE"
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"
    assert result["candidate_windows"]
    top = result["candidate_windows"][0]
    assert top["agents_n"] >= 100


def test_busy_window_outside_coverage_is_incomplete() -> None:
    rows = _busy_agents_floor()
    result = _analyze(
        rows, busy_since=COVERAGE_END + 100, busy_until=COVERAGE_END + 3700
    )
    assert result["targets"]["busy_hour"]["status"] == "INCOMPLETE"


def test_declared_tab_floor_is_enforced() -> None:
    rows = _busy_agents_floor()
    activity = [_activity("initial", "prompt_idle", COVERAGE_START)]
    result = _analyze(rows, activity, required_tabs=("patches",))
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"
    for index in range(30):
        rows.append(_sample("next", "patches", BUSY_SINCE + index * 10.0))
    result = _analyze(rows, activity, required_tabs=("patches",))
    assert result["targets"]["jk_p95"]["status"] == "PASS"


def test_overwritten_samples_count_as_dropped() -> None:
    rows = _busy_agents_floor()
    rows[-1] = _sample("next", "agents", BUSY_SINCE + 1, paint_ms=5.0)
    rows[-1]["dropped_total"] = 3
    result = _analyze(rows)
    assert result["attribution"]["dropped_samples"] == 3


def test_prompt_open_close_modal_intervals_split_durations() -> None:
    activity = [
        _activity("initial", "prompt_idle", COVERAGE_START),
        _activity("prompt_opened", "prompt_active", 1_000.0),
        _activity("prompt_closed", "prompt_idle", 2_000.0),
        _activity("modal_opened", "modal_open", 3_000.0, screen="M", text_entry=False),
        _activity("modal_closed", "prompt_idle", 3_600.0, screen="M"),
    ]
    result = _analyze([], activity, busy_since=None, busy_until=None)
    prompt = result["prompt"]
    assert prompt["active_s"] == pytest.approx(1_000.0)
    assert prompt["idle_s"] == pytest.approx(18_400.0)
    assert prompt["modal_s"] == pytest.approx(600.0)
    assert result["targets"]["prompt_activity"]["status"] == "PASS"


def test_missing_prompt_evidence_is_incomplete() -> None:
    result = _analyze([], busy_since=None, busy_until=None)
    assert result["prompt"]["unknown_s"] == pytest.approx(COVERAGE_END - COVERAGE_START)
    assert result["targets"]["prompt_activity"]["status"] == "INCOMPLETE"


def test_per_tab_quantiles_use_sorted_interpolation() -> None:
    rows = [
        _sample("next", "agents", BUSY_SINCE + index, paint_ms=float(index + 1))
        for index in range(100)
    ]
    result = _analyze(rows, busy_since=BUSY_SINCE - 10, busy_until=BUSY_SINCE + 3_590)
    dist = result["busy"]["tabs"]["agents"]["distribution"]
    assert dist["n"] == 100
    assert dist["p50"] == pytest.approx(50.5)
    assert dist["max"] == pytest.approx(100.0)
