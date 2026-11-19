"""Tests for grouped error digests with true totals, coverage, and pruning."""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.error_digest import (
    digest_notification_note,
    prune_old_error_digests,
    render_error_digest,
)
from sase.axe.state import (
    append_error,
    mark_error_digest_sent,
    read_error_counts,
    read_errors,
    rotate_error_interval,
    write_last_error_digest_ts,
)
from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.notifications.senders import notify_axe_error_digest

import sase.axe._state_scheduler as sched


@pytest.fixture
def temp_state_dir(tmp_path: Path):
    """Isolate axe state and reset in-process error accounting."""
    state_dir = tmp_path / ".sase" / "axe"
    sched._pending_write_failures = 0
    sched._pending_corrupt_files = 0
    del sched._pending_increments[:]
    sched._pending_overflow = 0
    sched._logged_kinds.clear()
    with patch("sase.axe.state.axe_state_dir", return_value=state_dir):
        yield state_dir
    sched._pending_write_failures = 0
    sched._pending_corrupt_files = 0
    del sched._pending_increments[:]
    sched._pending_overflow = 0
    sched._logged_kinds.clear()


def _error(
    job: str,
    text: str,
    *,
    routine: str = "axe",
    timestamp: str = "2026-11-19T10:00:00-05:00",
    signature: str | None = None,
) -> dict:
    entry = {
        "timestamp": timestamp,
        "lumberjack": routine,
        "job": job,
        "error": text,
        "traceback": "tb",
    }
    if signature is not None:
        entry["failure_signature"] = signature
    return entry


def test_digest_reports_true_total_past_ring_cap(temp_state_dir: Path) -> None:
    for index in range(150):
        append_error(
            _error("agent_publication", f"boom {index}", signature=f"sig-{index:03d}")
        )
    pending = rotate_error_interval()
    assert len(pending) == 1
    record = pending[0]
    assert record["total"] == 150
    assert len(record["groups"]) == 150
    assert record["samples_kept"] == sched.ERROR_RING_CAP
    body = render_error_digest(record)
    assert "150 errors from 150 causes" in body
    assert f"{sched.ERROR_RING_CAP} samples kept" in body
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 0
    assert counter["pending_digests"][0]["interval_id"] == record["interval_id"]


def test_delayed_digest_covers_whole_interval(temp_state_dir: Path) -> None:
    start = datetime(2026, 11, 19, 10, 0, tzinfo=get_timezone())
    later = start + timedelta(hours=5)
    append_error(
        _error(
            "agent_publication",
            "storm failure 1",
            timestamp=start.isoformat(),
            signature="storm",
        )
    )
    append_error(
        _error(
            "housekeeping",
            "disk full",
            timestamp=(start + timedelta(hours=2)).isoformat(),
            signature="disk",
        )
    )
    counter_file = temp_state_dir / "error_counts.json"
    counter = read_error_counts()
    assert counter is not None
    counter["interval_start"] = start.isoformat()
    sched.write_json_value_atomic(counter_file, counter)
    with patch.object(sched._state, "get_timestamp", return_value=later.isoformat()):
        pending = rotate_error_interval()
    record = pending[0]
    assert record["total"] == 2
    assert record["interval_start"] == start.isoformat()
    assert record["interval_end"] == later.isoformat()
    body = render_error_digest(record)
    assert "2 errors from 2 causes" in body
    assert "10:00" in body and "15:00" in body
    note = digest_notification_note(record)
    assert note == "2 errors from 2 causes since 10:00"


def test_crash_after_snapshot_resends_once_without_double_count(
    temp_state_dir: Path,
) -> None:
    for index in range(5):
        append_error(_error("agent_publication", f"boom {index}", signature="storm"))
    first = rotate_error_interval()
    assert len(first) == 1
    assert first[0]["total"] == 5
    counter = read_error_counts()
    assert counter is not None
    assert counter["total"] == 0
    second = rotate_error_interval()
    assert len(second) == 1
    assert second[0]["interval_id"] == first[0]["interval_id"]
    assert second[0]["total"] == 5
    append_error(_error("housekeeping", "disk full", signature="disk"))
    third = rotate_error_interval()
    assert len(third) == 2
    totals = sorted(record["total"] for record in third)
    assert totals == [1, 5]
    mark_error_digest_sent(first[0]["interval_id"])
    leftover = rotate_error_interval()
    assert len(leftover) == 1
    assert leftover[0]["total"] == 1
    assert leftover[0]["interval_id"] != first[0]["interval_id"]


def test_rotation_resets_sample_ring_for_next_interval(
    temp_state_dir: Path,
) -> None:
    append_error(_error("agent_publication", "old storm", signature="storm"))
    first = rotate_error_interval()
    assert first[0]["samples_kept"] == 1
    assert read_errors() == []
    mark_error_digest_sent(first[0]["interval_id"])
    append_error(_error("housekeeping", "disk full", signature="disk"))
    second = rotate_error_interval()
    assert len(second) == 1
    assert second[0]["total"] == 1
    assert second[0]["samples_kept"] == 1
    assert len(second[0]["ring_samples"]) == 1
    assert second[0]["ring_samples"][0]["job"] == "housekeeping"
    body = render_error_digest(second[0])
    assert "1 error from 1 cause (1 sample kept)" in body


def test_write_failures_surface_as_gte_with_count(temp_state_dir: Path) -> None:
    append_error(_error("agent_publication", "boom", signature="storm"))
    counter = read_error_counts()
    assert counter is not None
    counter["write_failures"] = 3
    counter["corrupt_files"] = 1
    sched.write_json_value_atomic(temp_state_dir / "error_counts.json", counter)
    pending = rotate_error_interval()
    body = render_error_digest(pending[0])
    assert "≥1 error from 1 cause" in body
    assert "3 write failures" in body
    assert "1 corrupt file" in body
    note = digest_notification_note(pending[0])
    assert note.startswith("≥1 error from 1 cause since")


def test_loud_signature_plus_rare_ones_one_line_per_cause(
    temp_state_dir: Path,
) -> None:
    for index in range(20):
        append_error(
            _error(
                "agent_publication",
                f"storm failure number {index}",
                signature="storm",
            )
        )
    append_error(
        _error("housekeeping", "disk full on retention pass", signature="disk")
    )
    append_error(_error("orchestrator", "routine crash-looping", signature="crash"))
    append_error(_error("sdd-sidecar", "clone recovery failed", signature="clone"))
    pending = rotate_error_interval()
    record = pending[0]
    assert record["total"] == 23
    jobs = {group["job"] for group in record["groups"]}
    assert jobs == {
        "agent_publication",
        "housekeeping",
        "orchestrator",
        "sdd-sidecar",
    }
    body = render_error_digest(record)
    assert "23 errors from 4 causes" in body
    assert body.count("\nCause ") == 4
    assert "  20  axe/agent_publication" in body
    assert "   1  axe/housekeeping" in body
    assert "   1  axe/orchestrator" in body
    assert "   1  axe/sdd-sidecar" in body


def test_retry_notify_does_not_create_second_row(temp_state_dir: Path) -> None:
    append_error(_error("agent_publication", "boom", signature="storm"))
    record = rotate_error_interval()[0]
    created: list[Notification] = []

    def _create(notification: Notification) -> None:
        created.append(notification)

    with (
        patch("sase.notifications.senders.upsert_notification", side_effect=_create),
        patch(
            "sase.notifications.senders.load_notifications",
            side_effect=lambda include_dismissed=False: list(created),
        ),
    ):
        notify_axe_error_digest(record=record)
        notify_axe_error_digest(record=record)
    assert len(created) == 1
    assert created[0].dedup_key == f"axe-error-digest:{record['interval_id']}"
    assert created[0].action == "ViewErrorReport"
    report = Path(created[0].action_data["error_report_path"])
    assert report.exists()
    assert "1 error from 1 cause" in report.read_text(encoding="utf-8")


def test_last_error_digest_ts_write_is_atomic(temp_state_dir: Path) -> None:
    ts = "2026-11-19T15:02:00-05:00"
    write_last_error_digest_ts(ts)
    path = temp_state_dir / "last_error_digest_ts"
    assert path.read_text() == ts
    temps = list(temp_state_dir.glob(".last_error_digest_ts.*.tmp"))
    assert temps == []


def test_pruning_removes_old_files_but_keeps_floor(tmp_path: Path) -> None:
    digest_dir = tmp_path / "error_digests"
    digest_dir.mkdir()
    now = 1_000_000_000.0
    day = 86400.0
    for index in range(60):
        path = digest_dir / f"digest_old_{index:02d}.txt"
        path.write_text("old\n", encoding="utf-8")
        os.utime(path, (now - 40 * day, now - 40 * day))
    for index in range(10):
        path = digest_dir / f"digest_new_{index:02d}.txt"
        path.write_text("new\n", encoding="utf-8")
        os.utime(path, (now - index, now - index))

    deleted = prune_old_error_digests(
        now=now,
        max_age_days=30.0,
        keep_count=50,
        min_interval_seconds=0,
        digest_dir=digest_dir,
    )
    remaining = sorted(path.name for path in digest_dir.glob("digest_*.txt"))
    assert deleted == 20
    assert len(remaining) == 50
    assert all(
        name.startswith("digest_new_") or name >= "digest_old_20" for name in remaining
    )

    again = prune_old_error_digests(
        now=now + 60.0,
        max_age_days=30.0,
        keep_count=0,
        min_interval_seconds=86400.0,
        digest_dir=digest_dir,
    )
    assert again == 0
