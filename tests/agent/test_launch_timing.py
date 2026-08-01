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

    assert records[0]["slow_stage_count"] == 1
    elapsed_ms = records[0]["stages"][0]["elapsed_ms"]
    assert records[0]["stages"] == [
        {
            "stage": "blocked_stage",
            "elapsed_ms": elapsed_ms,
            "slow_stage": True,
        }
    ]
    assert "slow_launch_stage" in caplog.text
    assert "stage=blocked_stage" in caplog.text
    assert "target=sase-test" in caplog.text
