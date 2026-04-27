"""Tests for the Phase-5 agent snapshot cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._snapshot_cache import AgentSnapshotCache
from sase.ace.tui.models.agent import AttemptRecord
from sase.llm_provider.retry_config import RetryState


def _write_attempt(artifacts_dir: Path, n: int, *, status: str = "failed") -> Path:
    sub = artifacts_dir / "attempts" / f"{n:02d}"
    sub.mkdir(parents=True, exist_ok=True)
    meta = {
        "attempt_number": n,
        "status": status,
        "start_epoch": 100.0 + n,
        "end_epoch": 150.0 + n,
        "model": "claude-sonnet-4-5",
        "used_fallback": False,
        "error_snippet": "boom",
        "error_full": "boom full",
    }
    meta_path = sub / "attempt_meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (sub / "live_reply.md").write_text(f"reply {n}", encoding="utf-8")
    (sub / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")
    return meta_path


def test_attempt_history_warm_hit_avoids_reparse(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agentX"
    artifacts_dir.mkdir()
    _write_attempt(artifacts_dir, 1)
    _write_attempt(artifacts_dir, 2)

    cache = AgentSnapshotCache()

    real_load = __import__(
        "sase.ace.tui.models.agent", fromlist=["load_attempt_history"]
    ).load_attempt_history
    call_count = 0

    def counting(path: str | None) -> list[AttemptRecord]:
        nonlocal call_count
        call_count += 1
        return real_load(path)

    with patch("sase.ace.tui.models.agent.load_attempt_history", side_effect=counting):
        first = cache.attempt_history_for(str(artifacts_dir))
        second = cache.attempt_history_for(str(artifacts_dir))

    assert call_count == 1
    assert [r.attempt_number for r in first] == [1, 2]
    assert [r.attempt_number for r in second] == [1, 2]


def test_attempt_history_invalidates_on_meta_mtime_change(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    meta = _write_attempt(artifacts_dir, 1)

    cache = AgentSnapshotCache()
    cache.attempt_history_for(str(artifacts_dir))

    st = meta.stat()
    os.utime(meta, ns=(st.st_mtime_ns + 1_000_000_000, st.st_mtime_ns + 1_000_000_000))

    real_load = __import__(
        "sase.ace.tui.models.agent", fromlist=["load_attempt_history"]
    ).load_attempt_history
    call_count = 0

    def counting(path: str | None) -> list[AttemptRecord]:
        nonlocal call_count
        call_count += 1
        return real_load(path)

    with patch("sase.ace.tui.models.agent.load_attempt_history", side_effect=counting):
        cache.attempt_history_for(str(artifacts_dir))

    assert call_count == 1


def test_attempt_history_picks_up_new_attempt_dir(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    _write_attempt(artifacts_dir, 1)

    cache = AgentSnapshotCache()
    first = cache.attempt_history_for(str(artifacts_dir))
    assert [r.attempt_number for r in first] == [1]

    _write_attempt(artifacts_dir, 2)
    second = cache.attempt_history_for(str(artifacts_dir))
    assert [r.attempt_number for r in second] == [1, 2]


def test_attempt_history_handles_missing_dir(tmp_path: Path) -> None:
    cache = AgentSnapshotCache()
    assert cache.attempt_history_for(None) == []
    assert cache.attempt_history_for(str(tmp_path / "missing")) == []


def test_retry_state_warm_hit(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    state = RetryState(status="retrying", retry_count=1, max_retries=3, wait_seconds=10)
    state.write_to(str(artifacts_dir))

    cache = AgentSnapshotCache()
    real_read = RetryState.read_from

    with patch.object(RetryState, "read_from", side_effect=real_read) as spy:
        first = cache.retry_state_for(str(artifacts_dir))
        second = cache.retry_state_for(str(artifacts_dir))

    assert spy.call_count == 1
    assert first is not None and first.retry_count == 1
    assert second is first


def test_retry_state_returns_none_when_missing(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()

    cache = AgentSnapshotCache()
    assert cache.retry_state_for(str(artifacts_dir)) is None
    # Cached miss should not call read_from again.
    with patch.object(RetryState, "read_from") as mock_read:
        cache.retry_state_for(str(artifacts_dir))
    mock_read.assert_not_called()


def test_retry_state_invalidates_on_size_change(tmp_path: Path) -> None:
    from sase.llm_provider.retry_config import RETRY_STATE_FILENAME

    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    RetryState(
        status="retrying", retry_count=1, max_retries=3, wait_seconds=10
    ).write_to(str(artifacts_dir))

    cache = AgentSnapshotCache()
    first = cache.retry_state_for(str(artifacts_dir))
    assert first is not None and first.retry_count == 1

    RetryState(
        status="retrying",
        retry_count=2,
        max_retries=3,
        wait_seconds=20,
        last_error_snippet="size-bump",
    ).write_to(str(artifacts_dir))
    # Force a mtime tick so the cache signature mismatches even on
    # filesystems with coarse mtime resolution.
    path = artifacts_dir / RETRY_STATE_FILENAME
    st = path.stat()
    os.utime(path, ns=(st.st_mtime_ns + 5_000_000_000, st.st_mtime_ns + 5_000_000_000))

    second = cache.retry_state_for(str(artifacts_dir))
    assert second is not None and second.retry_count == 2


def test_idle_refresh_does_zero_attempt_history_reads(tmp_path: Path) -> None:
    """Acceptance: idle auto-refresh re-reads no attempt history when nothing changed."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write_attempt(a, 1)
    _write_attempt(a, 2)
    _write_attempt(b, 1)

    cache = AgentSnapshotCache()
    cache.attempt_history_for(str(a))
    cache.attempt_history_for(str(b))

    real_load = __import__(
        "sase.ace.tui.models.agent", fromlist=["load_attempt_history"]
    ).load_attempt_history
    calls: list[str | None] = []

    def counting(path: str | None) -> list[AttemptRecord]:
        calls.append(path)
        return real_load(path)

    with patch("sase.ace.tui.models.agent.load_attempt_history", side_effect=counting):
        # Simulate two more "auto refresh" cycles with no FS changes.
        for _ in range(2):
            cache.attempt_history_for(str(a))
            cache.attempt_history_for(str(b))

    assert calls == []


def test_invalidate_clears_per_agent_slot(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _write_attempt(a, 1)
    _write_attempt(b, 1)

    cache = AgentSnapshotCache()
    cache.attempt_history_for(str(a))
    cache.attempt_history_for(str(b))

    cache.invalidate(str(a))

    real_load = __import__(
        "sase.ace.tui.models.agent", fromlist=["load_attempt_history"]
    ).load_attempt_history
    calls: list[str | None] = []

    def counting(path: str | None) -> list[AttemptRecord]:
        calls.append(path)
        return real_load(path)

    with patch("sase.ace.tui.models.agent.load_attempt_history", side_effect=counting):
        cache.attempt_history_for(str(a))  # miss
        cache.attempt_history_for(str(b))  # hit

    assert calls == [str(a)]
