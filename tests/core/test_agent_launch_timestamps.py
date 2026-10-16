"""Tests for Rust-backed launch timestamp allocation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sase.core.agent_launch_facade import (
    LaunchTimestampBatchAllocator,
    _allocate_launch_timestamp_batch,
    reserve_launch_timestamp_batch,
    safe_launch_name,
)
from sase.agent.launch_submission import capture_launch_submitted_at


def test_allocate_launch_timestamp_batch_uses_rust_unique_seconds() -> None:
    pytest.importorskip("sase_core_rs")

    assert _allocate_launch_timestamp_batch(
        3,
        base_timestamp="260501_120000",
    ) == ["260501_120000", "260501_120001", "260501_120002"]


def test_reserve_launch_timestamp_batch_uses_global_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert reserve_launch_timestamp_batch(
        2,
        base_timestamp="260501_120000",
    ) == ["260501_120000", "260501_120001"]
    assert reserve_launch_timestamp_batch(
        2,
        base_timestamp="260501_120000",
    ) == ["260501_120002", "260501_120003"]

    state_path = (
        tmp_path / ".sase" / "agent_launch_timestamps" / "last_reserved_timestamp"
    )
    assert state_path.read_text(encoding="utf-8").strip() == "260501_120003"


def test_launch_timestamp_allocator_tracks_previous_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("HOME", str(tmp_path))
    allocator = LaunchTimestampBatchAllocator()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "sase.core.time.generate_timestamp",
            lambda: "260501_120000",
        )
        assert allocator.allocate(2) == ["260501_120000", "260501_120001"]
        assert allocator.allocate(2) == ["260501_120002", "260501_120003"]


def test_safe_launch_name_matches_launch_path_contract() -> None:
    assert safe_launch_name("feature/test:1") == "feature_test_1"


def test_launch_submission_stamp_is_utc_and_preserves_fractional_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.time.get_timezone",
        lambda: ZoneInfo("America/New_York"),
    )

    submitted = capture_launch_submitted_at(
        now=datetime(
            2026,
            6,
            16,
            12,
            0,
            0,
            900_000,
            tzinfo=timezone(timedelta(hours=-5)),
        )
    )
    assert submitted == "2026-06-16T17:00:00.900000Z"


def test_launch_submission_fanout_uses_one_stamp_and_ignores_ambient_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.launch_submission import stamp_launch_submission
    from sase.env_contracts import SASE_LAUNCH_SUBMITTED_AT_ENV

    monkeypatch.setenv(SASE_LAUNCH_SUBMITTED_AT_ENV, "2026-01-01T12:00:00Z")
    monkeypatch.setattr(
        "sase.agent.launch_submission.capture_launch_submitted_at",
        lambda: "2026-01-01T12:00:00.900000Z",
    )

    base, segments, stamp = stamp_launch_submission(
        None,
        [{"slot": "one"}, {"slot": "two"}, {"slot": "three"}],
    )

    assert stamp == "2026-01-01T12:00:00.900000Z"
    assert base[SASE_LAUNCH_SUBMITTED_AT_ENV] == stamp
    assert all(
        env is not None and env[SASE_LAUNCH_SUBMITTED_AT_ENV] == stamp
        for env in segments
    )
