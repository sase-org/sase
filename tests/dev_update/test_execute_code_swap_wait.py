"""Tests for execute_dev_update with a bounded code-swap wait."""

from __future__ import annotations

import fcntl
import os

from sase.core.paths import sase_subdir
from sase.dev_update import code_swap_lock as lock_mod
from sase.dev_update.code_swap_lock import (
    CodeSwapWait,
    code_swap_reader_lock,
)
from sase.dev_update.execute import execute_dev_update
from sase.dev_update.models import DevCommandResult
from tests.dev_update._execute_helpers import FakeRunner, plan


def test_execute_wait_succeeds_after_reader_releases() -> None:
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
        timeout_seconds=10.0, poll_seconds=1.0, clock=clock, sleep=sleep
    )
    runner = FakeRunner()
    try:
        result = execute_dev_update(plan(), run=runner, clock=clock, wait=wait)
    finally:
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(raw_fd)
        holder_path.unlink(missing_ok=True)
    assert result.changed is True
    assert result.outcomes[0].status == "updated"


def test_execute_prewait_timeout_returns_deferred_without_git() -> None:
    runner = FakeRunner()
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        now = [0.0]

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        wait = CodeSwapWait(
            timeout_seconds=2.0, poll_seconds=1.0, clock=clock, sleep=sleep
        )
        result = execute_dev_update(plan(), run=runner, clock=clock, wait=wait)

    assert result.changed is False
    assert result.outcomes[0].status == "failed"
    assert "deferred:" in result.outcomes[0].reason
    assert "after waiting" in result.outcomes[0].reason
    assert "plan.md" in result.outcomes[0].reason
    assert runner.calls == []


def test_execute_holderless_lock_race_revalidates_preflight() -> None:
    lock_path = sase_subdir("locks") / "code-swap-v2.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    raw_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(raw_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    now = [0.0]
    polls = [0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds
        polls[0] += 1
        if polls[0] == 1:
            try:
                fcntl.flock(raw_fd, fcntl.LOCK_UN)
            except OSError:
                pass

    wait = CodeSwapWait(
        timeout_seconds=10.0, poll_seconds=1.0, clock=clock, sleep=sleep
    )
    runner = FakeRunner()
    try:
        result = execute_dev_update(plan(), run=runner, clock=clock, wait=wait)
    finally:
        try:
            fcntl.flock(raw_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(raw_fd)
    assert result.changed is True
    status_calls = [
        call
        for call in runner.calls
        if call[0][:5] == ("git", "-C", "/repo", "status", "--porcelain")
    ]
    assert len(status_calls) == 2


def test_execute_wait_cancelled_returns_deferred() -> None:
    runner = FakeRunner()
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        now = [0.0]

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        wait = CodeSwapWait(
            timeout_seconds=30.0,
            poll_seconds=1.0,
            clock=clock,
            sleep=sleep,
            cancel_check=lambda: True,
        )
        result = execute_dev_update(plan(), run=runner, clock=clock, wait=wait)
    assert result.changed is False
    assert "deferred:" in result.outcomes[0].reason
    assert "cancelled" in result.outcomes[0].reason
    assert runner.calls == []


def test_execute_no_wait_deferral_unchanged() -> None:
    runner = FakeRunner()
    with code_swap_reader_lock(
        op="bead.work",
        command=("sase", "bead", "work", "plan.md"),
    ):
        result = execute_dev_update(plan(), run=runner)
    assert result.changed is False
    assert "deferred:" in result.outcomes[0].reason
    assert "re-run `sase update` when it finishes" in result.outcomes[0].reason
    assert ("git", "-C", "/repo", "merge", "--ff-only", "origin/main") not in [
        call[0] for call in runner.calls
    ]
