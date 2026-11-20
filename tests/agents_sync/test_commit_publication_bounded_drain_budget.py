"""Alarm-timer and cleanup-budget coverage for bounded agent-hood drains."""

from __future__ import annotations

from pathlib import Path
import signal
import time

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    git_sync_transaction,
    publication_cleanup,
)
from sase.agents_sync.commit_publication import publish_committed_agent_hood
from sase.agents_sync.git import run_git
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._commit_publication_bounded_drain_helpers import (
    configure_target,
)


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires interval timers")
def test_bounded_drain_restores_an_existing_alarm_timer() -> None:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    try:
        signal.setitimer(signal.ITIMER_REAL, 5.0, 10.0)
        with publication_drain._bounded_publication_drain(1.0):
            pass
        delay, interval = signal.getitimer(signal.ITIMER_REAL)
        assert 4.0 < delay <= 5.0
        assert interval == 10.0
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def test_cleanup_budget_caps_cumulative_ops(tmp_path: Path) -> None:
    """Expired budgets refuse git and cumulative cleanup cannot overrun.

    Retry/age-wait budget enforcement lives in Rust
    (``git_lock::tests::{expired_budgets_stop_before_retry_or_removal,shorter_than_next_backoff_stops_without_granting_delay,aged_lock_with_exhausted_caller_deadline_never_removes}``);
    this executor test proves the Python side never resets the shared
    deadline across families.
    """
    import subprocess
    from pathlib import Path as _Path

    from sase.agents_sync import git_sync_transaction
    from sase.agents_sync.publication_cleanup import (
        PublicationCleanupBudget,
        bounded_git_runner,
        default_publication_cleanup_timeout,
    )

    assert default_publication_cleanup_timeout() == 15.0

    # Expired budget refuses git without running it.
    expired = PublicationCleanupBudget(
        timeout_seconds=1.0, deadline=time.monotonic() - 0.1
    )
    assert expired.exhausted()
    calls: list = []

    def fake_base(cwd, args, *, network=False, op="agents_sync.git"):
        calls.append((cwd, args))
        return subprocess.CompletedProcess(args, 0, "", "")

    bounded = bounded_git_runner(fake_base, expired)
    result = bounded(_Path("/tmp"), ["status"])
    assert result.returncode == 128
    assert "budget exhausted" in (result.stderr or "")
    assert calls == []

    # Cumulative cleanup families share one deadline: an exhausted budget
    # reports unfinished cleanup without running git.
    monkey_budget = PublicationCleanupBudget(
        timeout_seconds=1.0, deadline=time.monotonic() - 0.1
    )
    calls.clear()
    error = git_sync_transaction.clean_publication_worktree(
        tmp_path,
        fake_base,
        remaining_timeout=monkey_budget.remaining_timeout,
    )
    assert error is not None and "budget exhausted" in error
    assert calls == []


def test_drain_work_timeout_leaves_cleanup_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_cleanup,
        "default_publication_cleanup_timeout",
        lambda: 15.0,
    )
    assert publication_drain._drain_work_timeout(120.0) == 105.0
    assert publication_drain._drain_work_timeout(15.0) == 7.5
    assert publication_drain._drain_work_timeout(10.0) == 5.0


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="requires interval timers")
def test_timeout_leaves_enough_reserve_for_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AgentOwnerIdentity("alice", "athena")
    configure_target(monkeypatch, tmp_path, owner)
    timings: list = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    monkeypatch.setattr(
        publication_drain,
        "_configured_publication_drain_timeout",
        lambda: 3.0,
    )
    monkeypatch.setattr(
        publication_cleanup,
        "default_publication_cleanup_timeout",
        lambda: 2.0,
    )

    def blocked_render(*_args, **_kwargs):
        time.sleep(30)  # sase-test-wait: exceeds the 1s work timeout

    calls = {"count": 0}

    def reserved_cleanup(_repo: Path, _runner: object, **_kwargs: object):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        time.sleep(1.2)  # sase-test-wait: must finish inside the 2s reserve
        return None

    monkeypatch.setattr(publication_locked, "publish_agent_hood", blocked_render)
    monkeypatch.setattr(
        git_sync_transaction,
        "clean_agents_payload_worktree",
        reserved_cleanup,
    )

    outcome = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert outcome.queued and not outcome.published
    assert outcome.error is not None and "did not complete within" in outcome.error
    assert timings[-1].cleanup_result == "completed"
    cleanup_seconds = timings[-1].stage_durations.get("cleanup", 0.0)
    assert cleanup_seconds >= 1.0
    assert cleanup_seconds < 2.5
