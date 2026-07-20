"""Tests for the bounded axe lifecycle journal."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.config import AxeConfig
from sase.axe.desired_state import write_desired_state
from sase.axe.lifecycle_journal import (
    append_lifecycle_event,
    lifecycle_journal_path,
    read_recent_lifecycle_events,
    read_recent_successful_starts,
)
from sase.axe.maintenance import start_maintenance
from sase.axe.orchestrator import Orchestrator
from sase.axe._process_start import AXE_START_SOURCE_ENV


@pytest.fixture
def axe_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    with patch("sase.axe.state.axe_state_dir", return_value=state_dir):
        yield state_dir


def test_journal_retains_complete_recent_records_within_byte_cap(
    axe_state_dir: Path,
) -> None:
    write_desired_state("running", source="test setup")
    with patch(
        "sase.axe.maintenance._process_identity",
        return_value={"start_ticks": 123, "boot_id": "boot-a"},
    ):
        maintenance = start_maintenance("test maintenance")
        for index in range(12):
            assert append_lifecycle_event(
                "start",
                "started",
                source=f"source-{index}",
                reason="published",
                orchestrator_pid=1000 + index,
                succeeded=True,
                timestamp_epoch=100.0 + index,
                max_bytes=2048,
            )

    journal = lifecycle_journal_path()
    assert journal.stat().st_size <= 2048
    raw_records = [json.loads(line) for line in journal.read_text().splitlines()]
    records = read_recent_lifecycle_events(limit=0)

    assert records == raw_records
    assert 1 < len(records) < 12
    assert records[-1]["source"] == "source-11"
    assert records[-1]["desired_state"]["state"] == "running"
    assert records[-1]["maintenance"] == maintenance
    assert read_recent_successful_starts(now=112.0, window_seconds=5) == records[-5:]
    assert all(record["schema_version"] == 1 for record in records)


def test_reader_skips_malformed_and_truncated_historical_rows(
    axe_state_dir: Path,
) -> None:
    del axe_state_dir
    assert append_lifecycle_event(
        "stop",
        "not_running",
        source="axe stop",
        reason="not running",
        succeeded=True,
        timestamp_epoch=200.0,
    )
    journal = lifecycle_journal_path()
    valid = journal.read_bytes()
    journal.write_bytes(b'{"broken":\n' + valid + b'{"schema_version":1')

    assert read_recent_lifecycle_events(limit=0) == [json.loads(valid)]


def test_orchestrator_records_actual_start_source_after_pid_publication(
    axe_state_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AXE_START_SOURCE_ENV, "ace startup")
    stale_marker = axe_state_dir / "maintenance.json"
    stale_marker.parent.mkdir(parents=True, exist_ok=True)
    stale_marker.write_text(
        json.dumps(
            {
                "reason": "abandoned update",
                "pid": 99999999,
                "started_at": "2026-07-20T12:00:00+00:00",
            }
        )
    )
    orchestrator = Orchestrator(AxeConfig(lumberjacks={}))

    def interrupt_sleep(_seconds: float) -> None:
        raise KeyboardInterrupt

    with (
        patch("sase.axe.orchestrator.init_telemetry"),
        patch("sase.axe.orchestrator.reap_stale_log_rotation_temps"),
        patch("sase.axe.orchestrator.time.sleep", side_effect=interrupt_sleep),
    ):
        assert orchestrator.run() is True

    records = read_recent_lifecycle_events(limit=0)
    assert len(records) == 1
    assert records[0]["event"] == "start"
    assert records[0]["outcome"] == "started"
    assert records[0]["source"] == "ace startup"
    assert records[0]["orchestrator_pid"] == os.getpid()
    assert records[0]["maintenance"] is None
    assert not stale_marker.exists()
