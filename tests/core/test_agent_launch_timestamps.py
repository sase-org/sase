"""Tests for Rust-backed launch timestamp allocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.agent_launch_facade import (
    LaunchTimestampBatchAllocator,
    _allocate_launch_timestamp_batch,
    reserve_launch_timestamp_batch,
    safe_launch_name,
)


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
