"""Slow-agent-load section for ``tools/tui_freeze_report`` (sase-1q5.8)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest


def _load_loads_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "tools" / "_tui_freeze_report_loads.py"
    sys.path.insert(0, str(path.parent))
    loader = importlib.util.spec_from_file_location("_tui_freeze_report_loads", path)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def _load_tool() -> ModuleType:
    from importlib.machinery import SourceFileLoader

    tool_path = Path(__file__).resolve().parents[1] / "tools" / "tui_freeze_report"
    loader = SourceFileLoader("tui_freeze_report_tool_loads", str(tool_path))
    spec = importlib.util.spec_from_file_location(
        "tui_freeze_report_tool_loads", tool_path, loader=loader
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


loads = _load_loads_module()


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _slow_full(
    ts: float,
    *,
    instance: str = "aaa",
    source: str = "roster_completion_retry",
    index_s: float | None = 0.5,
    artifact_source: str | None = None,
    repair_reason: str | None = None,
    load_kind: str | None = "full",
    include_new_fields: bool = True,
) -> dict:
    substages = {
        "dismissed_snapshot": 0.01,
        "decode": 0.02,
        "provider": 0.01,
        "projections": 0.01,
    }
    if index_s is not None:
        substages["index"] = index_s
    row: dict = {
        "timestamp": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
        "event": "tui_agent_load_slow",
        "pid": 12,
        "app_instance_id": instance,
        "source": source,
        "stages_seconds": {"disk": 2.5},
        "slow_stages": ["disk"],
        "disk_substages": substages,
    }
    if load_kind is not None:
        row["load_kind"] = load_kind
    if include_new_fields:
        row["artifact_source"] = artifact_source
        row["repair_reason"] = repair_reason
        row["tier"] = "tier1"
        row["complete_history"] = False
    return row


def test_index_stage_buckets_and_unrecorded_fields() -> None:
    rows = [
        _slow_full(1000.0, index_s=0.5, artifact_source="artifact_index"),
        _slow_full(1001.0, index_s=1.0, source="tier1_index_revalidate"),
        _slow_full(1002.0, index_s=4.999, source="tier1_index_revalidate"),
        _slow_full(1003.0, index_s=5.0, source="input_quiet_tier2_reconcile"),
        _slow_full(1004.0, index_s=15.0, source="input_quiet_tier2_reconcile"),
        _slow_full(1005.0, index_s=29.999, source="input_quiet_tier2_reconcile"),
        _slow_full(1006.0, index_s=30.0, source="sync_load"),
        _slow_full(
            1007.0,
            index_s=None,
            source="sync_load",
            include_new_fields=False,
        ),
        _slow_full(
            1008.0,
            load_kind="artifact_delta",
            index_s=40.0,
            source="delta_ignored",
        ),
        {
            "timestamp": datetime.fromtimestamp(1009.0, tz=UTC).isoformat(),
            "event": "capacity_gauge",
            "app_instance_id": "aaa",
            "source": "capacity",
        },
        _slow_full(
            1010.0,
            load_kind=None,
            index_s=0.2,
            source="legacy_full",
            include_new_fields=False,
        ),
    ]

    summary = loads.summarize_slow_agent_loads(rows, since=1000.0, until=13600.0)

    assert summary["slow_full_load_count"] == 9
    assert summary["slow_full_loads_per_hour"] == pytest.approx(
        9 * 3600.0 / 12600.0, abs=0.001
    )
    assert summary["index_stage_buckets"] == {
        "<1s": 2,
        "1-5s": 2,
        "5-15s": 1,
        "15-30s": 2,
        ">=30s": 1,
        "unrecorded": 1,
    }
    assert summary["artifact_source"] == {"artifact_index": 1, "unrecorded": 8}
    assert summary["repair_reason"] == {"unrecorded": 9}
    assert summary["sources"]["input_quiet_tier2_reconcile"] == 3
    assert "delta_ignored" not in summary["sources"]
    assert "legacy_full" in summary["sources"]


def test_boundary_index_values_land_in_the_higher_bucket() -> None:
    rows = [
        _slow_full(1.0, index_s=0.0),
        _slow_full(2.0, index_s=0.999),
        _slow_full(3.0, index_s=1.0),
        _slow_full(4.0, index_s=5.0),
        _slow_full(5.0, index_s=15.0),
        _slow_full(6.0, index_s=30.0),
        _slow_full(7.0, index_s=-1.0),
    ]
    summary = loads.summarize_slow_agent_loads(rows, since=0.0, until=10.0)
    assert summary["index_stage_buckets"] == {
        "<1s": 2,
        "1-5s": 1,
        "5-15s": 1,
        "15-30s": 1,
        ">=30s": 1,
        "unrecorded": 1,
    }


def test_per_hour_uses_requested_window() -> None:
    rows = [_slow_full(1000.0), _slow_full(1100.0)]
    summary = loads.summarize_slow_agent_loads(rows, since=1000.0, until=2800.0)
    assert summary["slow_full_load_count"] == 2
    assert summary["window_s"] == pytest.approx(1800.0)
    assert summary["slow_full_loads_per_hour"] == pytest.approx(4.0)


def test_text_section_renders_unrecorded_and_top_sources() -> None:
    summary = loads.summarize_slow_agent_loads(
        [
            _slow_full(
                1000.0,
                index_s=16.0,
                source="roster_completion_retry",
                artifact_source="artifact_index",
                repair_reason="artifact_index_lock_busy_served_cached",
            ),
            _slow_full(1001.0, index_s=0.4, source="roster_completion_retry"),
            _slow_full(1002.0, index_s=2.0, source="tier1_index_revalidate"),
        ],
        since=1000.0,
        until=4600.0,
    )
    text = loads.format_slow_agent_loads(summary)
    assert "slow agent loads: 3 full (3.00/h)" in text
    assert (
        "index stage: <1s 1; 1-5s 1; 5-15s 0; 15-30s 1; >=30s 0; unrecorded 0" in text
    )
    assert "artifact_source: unrecorded 2; artifact_index 1" in text
    assert (
        "repair_reason: unrecorded 2; artifact_index_lock_busy_served_cached 1" in text
    )
    assert "top sources: roster_completion_retry 2; tier1_index_revalidate 1" in text


def test_cli_emits_text_and_json_and_reads_rotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _load_tool()
    stalls = _write_jsonl(tmp_path / "tui_stalls.jsonl", [])
    startup = _write_jsonl(tmp_path / "tui_startup.jsonl", [])
    active = _write_jsonl(
        tmp_path / "tui_agent_loads.jsonl",
        [
            _slow_full(
                2000.0,
                instance="live",
                index_s=16.0,
                artifact_source="artifact_index",
                repair_reason="artifact_index_lock_busy_served_cached",
            )
        ],
    )
    _write_jsonl(
        tmp_path / "tui_agent_loads.jsonl.1",
        [_slow_full(1000.0, instance="rotated", index_s=0.4)],
    )

    code = tool.main(
        [
            "--path",
            str(stalls),
            "--startup-path",
            str(startup),
            "--loads-path",
            str(active),
            "--since",
            "500",
            "--until",
            "4100",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "instance live" in out
    assert "instance rotated" in out
    assert "slow agent loads: 1 full" in out
    assert "index stage: <1s 0; 1-5s 0; 5-15s 0; 15-30s 1; >=30s 0; unrecorded 0" in out
    assert "artifact_source: artifact_index 1" in out

    code = tool.main(
        [
            "--json",
            "--path",
            str(stalls),
            "--startup-path",
            str(startup),
            "--loads-path",
            str(active),
            "--since",
            "500",
            "--until",
            "4100",
            "--instance",
            "live",
            "--no-rotated",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["inputs"]["loads_path"] == str(active)
    live = payload["instances"]["live"]["slow_agent_loads"]
    assert live["slow_full_load_count"] == 1
    assert live["index_stage_buckets"]["15-30s"] == 1
    assert live["artifact_source"] == {"artifact_index": 1}
    assert live["repair_reason"] == {"artifact_index_lock_busy_served_cached": 1}
    assert "rotated" not in payload["instances"]
    # JSON implies acceptance; an empty stall window is INCOMPLETE.
    assert code == 1
