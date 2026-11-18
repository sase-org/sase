"""Tests for the bounded polling writer wait in code_swap_lock."""

from __future__ import annotations

import fcntl
import os

from sase.core.paths import sase_subdir
from sase.dev_update import code_swap_lock as lock_mod
from sase.dev_update.code_swap_lock import (
    ENV_DISABLE_CODE_SWAP_LOCK,
    CodeSwapWait,
    code_swap_advisory_reader_lock,
    code_swap_reader_lock,
    code_swap_readers_active,
    code_swap_writer_lock,
    wait_for_code_swap_readers,
)


def _fake_clock_sleep(start: float = 0.0):
    now = [start]
    calls = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        now[0] += seconds

    return clock, sleep, now, calls


def test_waiting_writer_acquires_after_reader_releases() -> None:
    lock_path = sase_subdir("locks") / "code-swap-v2.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(raw_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    holder_path = lock_mod._write_reader_holder(
        lock_mod._holder(
            op="bead.work",
            command=("sase", "bead", "work", "plan.md"),
        ),
        path=lock_mod._reader_holder_path(pid=os.getpid(), blocking=True),
    )
    assert holder_path is not None
    now = [0.0]
    seen: list[str] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass

    wait = CodeSwapWait(
        timeout_seconds=10.0,
        poll_seconds=1.0,
        on_wait=seen.append,
        clock=clock,
        sleep=sleep,
    )
    try:
        with code_swap_writer_lock(wait=wait) as writer:
            assert writer.acquired is True
            assert writer.waited is True
    finally:
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(raw_fd)
        holder_path.unlink(missing_ok=True)
    assert seen
    assert "sase bead work" in seen[0]
    assert "plan.md" in seen[0]


def test_writer_wait_timeout_reports_holder() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        clock, sleep, _now, _calls = _fake_clock_sleep()
        seen: list[str] = []
        wait = CodeSwapWait(
            timeout_seconds=3.0,
            poll_seconds=1.0,
            on_wait=seen.append,
            clock=clock,
            sleep=sleep,
        )
        with code_swap_writer_lock(wait=wait) as writer:
            assert writer.acquired is False
            assert writer.wait_stop == "timeout"
            assert writer.waited is True
            assert writer.blocked_by is not None
            assert "sase bead work" in writer.blocked_by
            assert "plan.md" in writer.blocked_by
        assert seen
        assert all("sase bead work" in item for item in seen)


def test_writer_wait_cancel_check_stops() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        clock, sleep, _now, _calls = _fake_clock_sleep()
        wait = CodeSwapWait(
            timeout_seconds=30.0,
            poll_seconds=1.0,
            clock=clock,
            sleep=sleep,
            cancel_check=lambda: True,
        )
        with code_swap_writer_lock(wait=wait) as writer:
            assert writer.acquired is False
            assert writer.wait_stop == "cancelled"


def test_writer_on_wait_fires_once_per_distinct_blocker() -> None:
    lock_path = sase_subdir("locks") / "code-swap-v2.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(raw_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    holder_path = lock_mod._write_reader_holder(
        lock_mod._holder(op="bead.work", command=("sase", "bead", "work", "one.md")),
        path=lock_mod._reader_holder_path(pid=os.getpid(), blocking=True),
    )
    assert holder_path is not None
    now = [0.0]
    seen: list[str] = []
    polls = [0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds
        polls[0] += 1
        if polls[0] == 2:
            holder_path.write_text(
                __import__("json").dumps(
                    lock_mod._holder(
                        op="bead.work",
                        command=("sase", "bead", "work", "two.md"),
                    ),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

    wait = CodeSwapWait(
        timeout_seconds=5.0,
        poll_seconds=1.0,
        on_wait=seen.append,
        clock=clock,
        sleep=sleep,
    )
    try:
        with code_swap_writer_lock(wait=wait) as writer:
            assert writer.acquired is False
            assert writer.wait_stop == "timeout"
    finally:
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(raw_fd)
        holder_path.unlink(missing_ok=True)
    assert len(seen) == 2
    assert "one.md" in seen[0]
    assert "two.md" in seen[1]


def test_new_reader_can_acquire_while_writer_waits() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        now = [0.0]
        acquired: list[bool] = []

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds
            with code_swap_reader_lock(
                op="bead.work",
                command=("sase", "bead", "work", "other.md"),
            ) as other:
                acquired.append(other.acquired)

        wait = CodeSwapWait(
            timeout_seconds=2.0, poll_seconds=1.0, clock=clock, sleep=sleep
        )
        with code_swap_writer_lock(wait=wait) as writer:
            assert writer.acquired is False
            assert writer.wait_stop == "timeout"
        assert acquired
        assert all(acquired)


def test_wait_none_is_unchanged_immediate() -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        with code_swap_writer_lock() as writer:
            assert writer.acquired is False
            assert writer.waited is False
            assert writer.wait_stop is None


def test_prewait_clears_after_release() -> None:
    lock_path = sase_subdir("locks") / "code-swap-v2.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(raw_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    holder_path = lock_mod._write_reader_holder(
        lock_mod._holder(op="bead.work", command=("sase", "bead", "work", "plan.md")),
        path=lock_mod._reader_holder_path(pid=os.getpid(), blocking=True),
    )
    assert holder_path is not None
    now = [0.0]
    seen: list[str] = []

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        holder_path.unlink(missing_ok=True)

    wait = CodeSwapWait(
        timeout_seconds=10.0,
        poll_seconds=1.0,
        on_wait=seen.append,
        clock=clock,
        sleep=sleep,
    )
    try:
        outcome = wait_for_code_swap_readers(wait)
        assert outcome.cleared is True
    finally:
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(raw_fd)
        holder_path.unlink(missing_ok=True)


def test_prewait_timeout_and_ignores_advisory(monkeypatch) -> None:
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        clock, sleep, _now, _calls = _fake_clock_sleep()
        wait = CodeSwapWait(
            timeout_seconds=2.0, poll_seconds=1.0, clock=clock, sleep=sleep
        )
        outcome = wait_for_code_swap_readers(wait)
        assert outcome.cleared is False
        assert outcome.timed_out is True
        assert outcome.blocked_by is not None
        assert "plan.md" in outcome.blocked_by

    with code_swap_advisory_reader_lock(op="agent.runner", command=("tg",)):
        assert code_swap_readers_active() is None
        clock, sleep, _now, _calls = _fake_clock_sleep()
        wait = CodeSwapWait(
            timeout_seconds=2.0, poll_seconds=1.0, clock=clock, sleep=sleep
        )
        outcome = wait_for_code_swap_readers(wait)
        assert outcome.cleared is True

    monkeypatch.setenv(ENV_DISABLE_CODE_SWAP_LOCK, "1")
    clock, sleep, _now, _calls = _fake_clock_sleep()
    wait = CodeSwapWait(timeout_seconds=2.0, poll_seconds=1.0, clock=clock, sleep=sleep)
    outcome = wait_for_code_swap_readers(wait)
    assert outcome.cleared is True
