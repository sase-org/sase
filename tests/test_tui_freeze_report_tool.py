"""Tests for the `tools/tui_freeze_report` CLI wrapper.

The report is driven against synthetic JSONL fixtures that mix pre-phase
rows (no ``app_instance_id``, no additive fields) with current rows, so old
logs keep reporting instead of breaking the acceptance tool.

Acceptance calculations live in ``tools/_tui_freeze_report_acceptance.py``.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone, UTC
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
        [
            {
                "timestamp": datetime.fromtimestamp(500.0, tz=UTC).isoformat(),
                "event": "tui_startup",
                "pid": 11,
            }
        ],
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


def test_idle_full_generation_p95_sorts_samples_before_quantile(
    tool: ModuleType,
) -> None:
    durations = [2.0, 0.1, 1.8, 0.2, 1.6, 0.3, 1.4, 0.4, 1.2, 0.5]
    rows = [
        {
            "ts": 1000.0 + index,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": duration,
            "trigger": "idle",
            "app_instance_id": "sorted",
        }
        for index, duration in enumerate(durations)
    ]

    summary = tool.summarize_instance(rows, since=1000.0, until=1100.0)

    assert summary["idle_pause_p95"] == pytest.approx(
        tool._percentile(sorted(durations), 0.95)
    )


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


def test_acceptance_empty_window_is_incomplete_and_nonzero(
    tool: ModuleType,
    stalls_path: Path,
    startup_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = tool.main(
        [
            "--path",
            str(stalls_path),
            "--startup-path",
            str(startup_path),
            "--since",
            "2000",
            "--until",
            "2010",
            "--acceptance",
        ]
    )

    assert code == 1
    output = capsys.readouterr().out
    assert "no diagnostic rows in window" in output
    assert "overall INCOMPLETE" in output


def test_json_mode_emits_versioned_acceptance_for_empty_selection(
    tool: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stalls = _write_jsonl(tmp_path / "empty-stalls.jsonl", [])
    startup = _write_jsonl(tmp_path / "empty-startup.jsonl", [])

    code = tool.main(
        [
            "--path",
            str(stalls),
            "--startup-path",
            str(startup),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["schema_version"] == 1
    assert payload["overall_status"] == "INCOMPLETE"
    assert (
        payload["instances"]["selection"]["acceptance"]["targets"]["coverage"]["status"]
        == "INCOMPLETE"
    )


def test_iso_timestamp_startup_windows_bucket_idless_rows(
    tool: ModuleType, tmp_path: Path
) -> None:
    stalls = _write_jsonl(
        tmp_path / "tui_stalls.jsonl",
        [{"ts": 600.0, "event": "tui_hitch", "pid": 11, "stall_seconds": 1.0}],
    )
    startup = _write_jsonl(
        tmp_path / "tui_startup.jsonl",
        [
            {
                "timestamp": "1970-01-01T00:08:20+00:00",
                "event": "tui_startup",
                "pid": 11,
            }
        ],
    )
    buckets = tool.bucket_by_instance(tool.load_rows(stalls), tool.load_rows(startup))
    assert "startup-0" in buckets
    assert "unknown" not in buckets
    assert len(buckets["startup-0"]) == 1


def test_iso_time_bounds_get_only_microsecond_rounding_tolerance(
    tool: ModuleType,
) -> None:
    assert tool.parse_time_tolerance("2026-10-24T12:00:00.123456Z") == pytest.approx(
        0.000001
    )
    assert tool.parse_time_tolerance("1792843200.123456") == 0.0


def test_load_stall_rows_includes_rotated_generation(
    tool: ModuleType, tmp_path: Path
) -> None:
    active = _write_jsonl(
        tmp_path / "tui_stalls.jsonl",
        [
            {
                "ts": 2000.0,
                "event": "tui_gc_pause",
                "generation": 2,
                "duration_s": 0.2,
                "trigger": "idle",
                "app_instance_id": "live",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "tui_stalls.jsonl.1",
        [
            {
                "ts": 1000.0,
                "event": "tui_gc_pause",
                "generation": 2,
                "duration_s": 0.3,
                "trigger": "backstop",
                "app_instance_id": "rotated",
            }
        ],
    )
    rows = tool.load_stall_rows(active)
    instances = {row["app_instance_id"] for row in rows}
    assert instances == {"live", "rotated"}
    opted_out = tool.load_stall_rows(active, include_rotated=False)
    assert {row["app_instance_id"] for row in opted_out} == {"live"}


def test_trigger_split_and_backstop_near_input(tool: ModuleType) -> None:
    rows = [
        {
            "ts": 1000.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 0.4,
            "trigger": "idle",
            "app_instance_id": "aaa",
        },
        {
            "ts": 1001.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 5.0,
            "trigger": "backstop",
            "input_age_s": 1.0,
            "app_instance_id": "aaa",
        },
        {
            "ts": 1002.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 1.2,
            "trigger": "rss_backstop",
            "input_age_s": 3.0,
            "app_instance_id": "aaa",
        },
        {
            "ts": 1003.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 0.05,
            "trigger": "automatic",
            "input_age_s": 0.2,
            "app_instance_id": "aaa",
        },
        {
            "ts": 1004.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 0.8,
            "trigger": "startup_freeze",
            "app_instance_id": "aaa",
        },
    ]
    summary = tool.summarize_instance(rows, since=1000.0, until=1010.0)
    assert summary["idle_pause_count"] == 1
    assert summary["pause_stats_by_trigger"]["backstop"]["count"] == 1
    assert summary["pause_stats_by_trigger"]["rss_backstop"]["count"] == 1
    assert summary["pause_stats_by_trigger"]["startup_freeze"]["count"] == 1
    assert summary["pause_stats_by_trigger"]["automatic"]["count"] == 1
    assert summary["auto_gen2_near_input"] == 1
    assert summary["backstop_gen2_near_input"] == 1
    assert summary["rss_backstop_gen2_near_input"] == 0


def test_heartbeat_hitch_totals_win_over_interval_union(tool: ModuleType) -> None:
    rows = [
        {
            "ts": 1000.0,
            "event": "tui_hitch",
            "stall_seconds": 2.0,
            "app_instance_id": "aaa",
        },
        {
            "ts": 1002.0,
            "event": "tui_hitch_recovered",
            "duration_seconds": 2.0,
            "app_instance_id": "aaa",
        },
        {
            "ts": 1010.0,
            "event": "tui_memory_heartbeat",
            "app_instance_id": "aaa",
            "loop_hitch_seconds": 12.0,
            "loop_suppressed_seconds": 4.0,
            "gc_generations": {"2": {"count": 1, "total_s": 1.0, "max_s": 1.0}},
        },
    ]
    summary = tool.summarize_instance(rows, since=1000.0, until=1030.0)
    assert summary["frozen_s"] == pytest.approx(12.0)
    assert summary["loop_hitch_seconds"] == pytest.approx(12.0)
    assert summary["loop_suppressed_seconds"] == pytest.approx(4.0)


def test_acceptance_marks_sase_1f3_targets(
    tool: ModuleType,
    stalls_path: Path,
    startup_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = tool.main(
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
            "--acceptance",
            "--no-rotated",
        ]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "acceptance (sase-1f3)" in out
    assert "INCOMPLETE" in out
    assert "Agents j/k p95" in out


def test_acceptance_does_not_pass_short_window_without_instance_provenance(
    tool: ModuleType,
) -> None:
    rows = [
        {
            "ts": 1000.0,
            "event": "tui_memory_heartbeat",
            "app_instance_id": "clean",
            "rss_bytes": 100 * 1024 * 1024,
            "vmswap_bytes": 0,
            "loop_hitch_seconds": 0.0,
            "loop_suppressed_seconds": 0.0,
            "gc_generations": {"2": {"count": 1, "total_s": 0.1, "max_s": 0.1}},
        },
        {
            "ts": 1001.0,
            "event": "tui_gc_pause",
            "generation": 2,
            "duration_s": 0.1,
            "trigger": "idle",
            "input_age_s": 5.0,
            "app_instance_id": "clean",
        },
        {
            "ts": 1002.0,
            "event": "tui_memory_heartbeat",
            "app_instance_id": "clean",
            "rss_bytes": 110 * 1024 * 1024,
            "vmswap_bytes": 0,
            "loop_hitch_seconds": 0.0,
            "loop_suppressed_seconds": 0.0,
            "gc_generations": {"2": {"count": 0, "total_s": 0.0, "max_s": 0.0}},
        },
    ]
    result = tool.analyze_acceptance(
        rows,
        [],
        "clean",
        requested_since=1000.0,
        requested_until=1100.0,
    )
    assert result["overall_status"] == "INCOMPLETE"
    assert result["targets"]["coverage"]["status"] == "INCOMPLETE"
    assert result["targets"]["jk_p95"]["status"] == "INCOMPLETE"


def test_cli_joins_rotated_perf_and_heartbeat_activity(tmp_path, tool, capsys) -> None:
    from tests.test_tui_freeze_report_acceptance import (
        FIRST_HEARTBEAT_TS,
        INSTANCE,
        _heartbeat,
        _startup,
    )

    start = FIRST_HEARTBEAT_TS
    end = start + 14_400
    rows = []
    for index in range(49):
        wall = start + index * 300
        row = _heartbeat(
            wall, wall - 300, gc_count=int(index > 0), gc_seconds=0.1 if index else 0
        )
        row["prompt_activity"] = {
            "event": "prompt_activity",
            "app_instance_id": INSTANCE,
            "pid": 41,
            "transition": "checkpoint",
            "sequence": 0 if index == 0 else 2,
            "state": "prompt_idle",
            "t_wall": wall,
            "t_mono": wall,
        }
        rows.append(row)
        if index:
            rows.append(
                {
                    "event": "tui_gc_pause",
                    "app_instance_id": INSTANCE,
                    "start_ts": wall - 10,
                    "ts": wall - 9.9,
                    "duration_s": 0.1,
                    "generation": 2,
                    "trigger": "idle",
                    "input_age_s": 5,
                }
            )
    for offset, state, sequence in ((100, "prompt_active", 1), (200, "prompt_idle", 2)):
        rows.append(
            {
                "event": "prompt_activity",
                "app_instance_id": INSTANCE,
                "t_wall": start + offset,
                "t_mono": start + offset,
                "state": state,
                "sequence": sequence,
                "transition": "changed",
            }
        )
    stalls = _write_jsonl(tmp_path / "stalls.jsonl", rows)
    startups = _write_jsonl(tmp_path / "startups.jsonl", [_startup()])
    samples = [
        {
            "action": "next",
            "tab": "agents",
            "pid": 41,
            "app_instance_id": INSTANCE,
            "t_wall": start + (index % 4) * 600 + index // 4,
            "t_keypress": start + (index % 4) * 600 + index // 4,
            "model_ms": 1,
            "paint_ms": 5,
        }
        for index in range(100)
    ]
    perf_path = tmp_path / "perf.jsonl"
    _write_jsonl(Path(f"{perf_path}.1"), samples)
    args = [
        "--json",
        "--path",
        str(stalls),
        "--startup-path",
        str(startups),
        "-p",
        str(perf_path),
        "--instance",
        INSTANCE,
        "--since",
        str(start),
        "--until",
        str(end),
        "-b",
        str(start),
        "-e",
        str(start + 3600),
    ]
    assert tool.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["instances"][INSTANCE]["acceptance"]
    assert result["overall_status"] == "PASS"
    assert result["perf"]["attribution"]["attributed_samples"] == 100
    assert result["perf"]["prompt"]["active_s"] == 100
    assert payload["inputs"]["perf_path"] == str(perf_path)
    assert tool.main([*args, "--no-rotated"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert (
        payload["instances"][INSTANCE]["acceptance"]["targets"]["jk_p95"]["status"]
        == "INCOMPLETE"
    )
