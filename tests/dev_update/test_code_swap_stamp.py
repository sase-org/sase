"""Tests for the durable last-swap stamp written on code-swap writer release."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.dev_update import code_swap_lock as lock_mod
from sase.dev_update import code_swap_stamp as stamp_mod
from sase.dev_update.code_swap_lock import (
    ENV_DISABLE_CODE_SWAP_LOCK,
    code_swap_lock_path,
    code_swap_reader_lock,
    code_swap_writer_holder,
    code_swap_writer_lock,
)
from sase.dev_update.code_swap_stamp import (
    CODE_SWAP_GRACE_SECONDS,
    CODE_SWAP_LAST_SWAP_FILENAME,
    _LastCodeSwap,
    _last_code_swap_path,
    read_last_code_swap,
    recent_code_swap,
    record_last_code_swap,
)


def _write_stamp(payload: object) -> Path:
    path = _last_code_swap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stamp(
    *, completed_ago: float, duration: float = 5.0, generation: int = 3
) -> dict[str, object]:
    completed = datetime.now(UTC) - timedelta(seconds=completed_ago)
    return {
        "op": "dev.update",
        "pid": 1,
        "started_at": (completed - timedelta(seconds=duration)).isoformat(),
        "completed_at": completed.isoformat(),
        "generation": generation,
    }


def test_stamp_lives_next_to_the_writer_lock() -> None:
    assert _last_code_swap_path().parent == code_swap_lock_path().parent
    assert _last_code_swap_path().name == CODE_SWAP_LAST_SWAP_FILENAME


def test_writer_release_records_stamp_with_increasing_generation() -> None:
    assert read_last_code_swap() is None

    before = datetime.now(UTC)
    with code_swap_writer_lock() as lock:
        assert lock.acquired is True
        assert read_last_code_swap() is None  # recorded on release, not acquire
    first = read_last_code_swap()
    after = datetime.now(UTC)

    assert first is not None
    assert first.op == "dev.update"
    assert first.generation == 1
    assert before <= first.started_at <= first.completed_at <= after

    with code_swap_writer_lock() as lock:
        assert lock.acquired is True
    second = read_last_code_swap()
    assert second is not None
    assert second.generation == 2
    assert second.started_at >= first.completed_at


def test_waiting_writer_release_records_stamp() -> None:
    wait = lock_mod.CodeSwapWait(timeout_seconds=1.0, poll_seconds=0.01)
    with code_swap_writer_lock(wait=wait) as lock:
        assert lock.acquired is True
    swap = read_last_code_swap()
    assert swap is not None
    assert swap.generation == 1


def test_stamp_is_recorded_when_the_swap_body_raises() -> None:
    with pytest.raises(RuntimeError, match="swap blew up"):
        with code_swap_writer_lock() as lock:
            assert lock.acquired is True
            raise RuntimeError("swap blew up")

    assert read_last_code_swap() is not None
    assert code_swap_writer_holder() is None


def test_stamp_is_written_before_the_writer_holder_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prober must always see either the live writer or the finished swap."""
    seen: list[str | None] = []
    real_record = lock_mod.record_last_code_swap

    def _record(**kwargs: str) -> _LastCodeSwap | None:
        seen.append(code_swap_writer_holder())
        return real_record(**kwargs)

    monkeypatch.setattr(lock_mod, "record_last_code_swap", _record)
    with code_swap_writer_lock() as lock:
        assert lock.acquired is True

    assert len(seen) == 1
    assert seen[0] is not None and "sase dev update" in seen[0]


def test_refused_writer_records_no_stamp() -> None:
    with code_swap_reader_lock(op="bead.work", command=("sase", "bead", "work")):
        with code_swap_writer_lock() as lock:
            assert lock.acquired is False
    assert read_last_code_swap() is None


def test_disabled_lock_records_and_reads_no_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_stamp(_stamp(completed_ago=1.0))
    monkeypatch.setenv(ENV_DISABLE_CODE_SWAP_LOCK, "1")
    assert read_last_code_swap() is None
    assert recent_code_swap() is None

    stamp_before = _last_code_swap_path().read_text(encoding="utf-8")
    with code_swap_writer_lock() as lock:
        assert lock.acquired is True
    assert _last_code_swap_path().read_text(encoding="utf-8") == stamp_before


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        ["a", "list"],
        {"op": "dev.update"},
        {**_stamp(completed_ago=1.0), "generation": 0},
        {**_stamp(completed_ago=1.0), "generation": True},
        {**_stamp(completed_ago=1.0), "generation": "4"},
        {**_stamp(completed_ago=1.0), "op": ""},
        {**_stamp(completed_ago=1.0), "completed_at": "yesterday"},
        {**_stamp(completed_ago=1.0), "started_at": None},
    ],
    ids=[
        "garbage",
        "non-object",
        "missing-fields",
        "zero-generation",
        "bool-generation",
        "string-generation",
        "empty-op",
        "bad-completed-at",
        "missing-started-at",
    ],
)
def test_corrupt_stamp_reads_as_no_swap(payload: object) -> None:
    path = _last_code_swap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        _write_stamp(payload)

    assert read_last_code_swap() is None
    assert recent_code_swap() is None


def test_corrupt_stamp_restarts_the_generation() -> None:
    _write_stamp({"generation": "garbage"})
    swap = record_last_code_swap(
        op="dev.update", started_at="2026-11-20T00:00:00+00:00"
    )
    assert swap is not None
    assert swap.generation == 1
    assert read_last_code_swap() == swap


def test_naive_timestamps_are_read_as_utc() -> None:
    _write_stamp(
        {
            "op": "install.dev",
            "started_at": "2026-11-20T10:00:00",
            "completed_at": "2026-11-20T10:00:30",
            "generation": 9,
        }
    )
    swap = read_last_code_swap()
    assert swap is not None
    assert swap.completed_at == datetime(2026, 11, 20, 10, 0, 30, tzinfo=UTC)
    assert "just install-dev swap #9" in swap.describe()


def test_recent_code_swap_honors_the_grace_window() -> None:
    _write_stamp(_stamp(completed_ago=CODE_SWAP_GRACE_SECONDS - 10))
    assert recent_code_swap() is not None

    _write_stamp(_stamp(completed_ago=CODE_SWAP_GRACE_SECONDS + 10))
    assert recent_code_swap() is None


def test_future_stamp_cannot_inhibit_forever() -> None:
    _write_stamp(_stamp(completed_ago=-(CODE_SWAP_GRACE_SECONDS + 60)))
    assert recent_code_swap() is None


def test_overlap_requires_the_run_to_span_the_swap() -> None:
    base = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    swap = _LastCodeSwap(
        op="dev.update",
        started_at=base,
        completed_at=base + timedelta(seconds=10),
        generation=1,
    )
    second = timedelta(seconds=1)

    assert swap.overlaps(base - second, base + second)  # ran into the swap
    assert swap.overlaps(base + 2 * second, base + 5 * second)  # inside it
    assert swap.overlaps(base + 9 * second, base + 30 * second)  # ran out of it
    assert swap.overlaps(base - second, base)  # finished as it started
    assert not swap.overlaps(base - 5 * second, base - second)  # done before
    assert not swap.overlaps(base + 10 * second, base + 20 * second)  # began after


def test_record_failure_never_blocks_release(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(stamp_mod, "_write_atomic", _boom)
    with code_swap_writer_lock() as lock:
        assert lock.acquired is True
    assert read_last_code_swap() is None
    assert code_swap_writer_holder() is None
