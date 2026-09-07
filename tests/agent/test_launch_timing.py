from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.agent.launch_timing import LaunchTimingRecorder


def test_slow_stage_is_marked_and_warned(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sase.logs.log_tui_launch_timing",
        records.append,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="sase.agent.launch_timing",
    ):
        with LaunchTimingRecorder(
            "bead_work",
            {"bead_id": "sase-test"},
            durable=True,
            slow_stage_threshold_seconds=0.0,
        ) as timer:
            with timer.stage("blocked_stage"):
                pass

    summary = next(record for record in records if record["event"] == "launch_timing")
    elapsed_ms = summary["stages"][0]["elapsed_ms"]
    assert summary["slow_stage_count"] == 1
    assert summary["stages"] == [
        {
            "stage": "blocked_stage",
            "stage_id": 1,
            "elapsed_ms": elapsed_ms,
            "slow_stage": True,
        }
    ]
    assert "slow_launch_stage" in caplog.text
    assert "stage=blocked_stage" in caplog.text
    assert "target=sase-test" in caplog.text


def test_durable_stage_events_preserve_nested_parentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, Any]] = []
    monkeypatch.setattr("sase.logs.log_tui_launch_timing", records.append)

    with LaunchTimingRecorder(
        "bead_work",
        {"bead_id": "sase-test", "correlation_id": "corr-1"},
        durable=True,
    ) as timer:
        with timer.stage("parent"):
            with timer.stage("child", relevant_row_reads=1):
                pass

    stage_records = [
        record for record in records if record["event"] == "launch_timing_stage"
    ]
    summary = next(record for record in records if record["event"] == "launch_timing")
    child, parent = stage_records

    assert child["stage"] == "child"
    assert child["parent_stage"] == "parent"
    assert child["parent_stage_id"] == parent["stage_id"]
    assert child["correlation_id"] == "corr-1"
    assert parent["stage"] == "parent"
    assert summary["stage_count"] == 2
    assert [stage["stage"] for stage in summary["stages"]] == ["child", "parent"]


def test_progress_writes_to_stderr_not_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with LaunchTimingRecorder(
        "bead_work",
        {"resolved_epic_id": "sase-test"},
        progress=True,
        progress_interval_seconds=0.0,
    ) as timer:
        with timer.stage("owner_discovery", completed_owners=1, total_owners=3):
            pass

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "launch_timing target=sase-test stage=owner_discovery" in captured.err
    assert "owners=1/3" in captured.err
