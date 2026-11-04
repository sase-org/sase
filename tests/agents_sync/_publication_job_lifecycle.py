"""Readiness, scheduling, and lock tests for the publication job."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import signal
import time
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_queue as publication_queue
from sase.agents_sync import publication_doorbell, publication_job
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.git_sync_ops import bounded_agents_lock
from sase.agents_sync.publication_outbox import (
    enqueue_agent_publication,
    list_agent_publications,
)
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import (
    publication_hint,
    publication_item,
    publication_target,
)


def test_new_publication_waits_for_done_marker_or_ten_minute_grace(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "run"
    item = publication_item(
        "alice.athena.worker",
        "a" * 40,
        created_at=1_000,
        artifacts_dir=artifacts_dir,
    )

    assert not publication_job._publication_is_ready(item, now=1_599)
    assert publication_job._publication_is_ready(item, now=1_600)

    artifacts_dir.mkdir()
    (artifacts_dir / "done.json").write_text("{}", encoding="utf-8")
    assert publication_job._publication_is_ready(item, now=1_001)


def test_publication_job_leaves_young_request_queued_until_done_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    artifacts_dir = tmp_path / "run"
    artifacts_dir.mkdir()
    item = publication_item(
        "alice.athena.worker",
        "a" * 40,
        created_at=time.time(),
        artifacts_dir=artifacts_dir,
        run_id="run-1",
    )
    queue = [item]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        publication_queue,
        "drain_selected_agent_publications",
        lambda *_args, **_kwargs: pytest.fail("young request must stay queued"),
    )

    outcome = publication_job._drain_project(
        publication_target(tmp_path),
        deadline=time.monotonic() + 10,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    assert queue == [item]
    assert item.attempts == 0
    assert outcome.hood_drained == 0
    assert outcome.outcome == "awaiting_done_marker"


def test_busy_agents_lock_rings_again_without_charging_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    queue = [item]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job, "list_referenced_by_requests", lambda *_a, **_k: ()
    )
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_a, **_k: [
            SimpleNamespace(
                project_name="proj", workspace_dir="/tmp/proj", is_project=True
            )
        ],
    )
    target = publication_target(tmp_path)
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, hint=None: bells.append(key),
    )
    monkeypatch.setattr(
        publication_queue,
        "drain_selected_agent_publications",
        lambda *_a, **_k: CommitPublicationOutcome(
            queued=True,
            error="agents sync lock is busy",
        ),
    )
    publication_doorbell.ring_publication_doorbell(
        "proj", publication_hint("alice.athena.worker", "a" * 40)
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.lock_busy == 1
    assert summary.active_remaining == 1
    assert bells == ["proj"]
    assert queue[0].attempts == 0
    assert summary.project_stats["proj"]["last_outcome"] == "lock_busy"


def test_budget_defers_projects_without_starting_a_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: (item,)
    )
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_a, **_k: [
            SimpleNamespace(
                project_name="proj", workspace_dir="/tmp/proj", is_project=True
            )
        ],
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(
            targets=(publication_target(tmp_path),), outcomes=()
        ),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, hint=None: bells.append(key),
    )
    monkeypatch.setattr(
        publication_job,
        "_drain_project",
        lambda *_a, **_k: pytest.fail("drain must not start after the budget expires"),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=0)

    assert summary.deferred_projects == 1
    assert summary.project_stats["proj"]["last_outcome"] == "deferred_budget"
    assert bells == ["proj"]


def _hold_publication_locks(
    ready: multiprocessing.synchronize.Event, path: str
) -> None:
    with publication_job._publisher_job_lock() as job_acquired:
        with bounded_agents_lock(Path(path), 2, operation="test-publisher") as acquired:
            if job_acquired and acquired:
                ready.set()
                while True:
                    time.sleep(1)  # sase-test-wait: wait for parent SIGKILL


@pytest.mark.skipif(os.name != "posix", reason="publisher locks use POSIX flock")
def test_sigkilled_publisher_leaves_request_active_and_releases_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    enqueue_agent_publication(
        publication_item("alice.athena.worker", "a" * 40, created_at=1)
    )
    lock_path = tmp_path / "agents" / "sase-agents-sync.lock"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    process = context.Process(
        target=_hold_publication_locks, args=(ready, str(lock_path))
    )
    process.start()
    try:
        assert ready.wait(5)
        os.kill(process.pid, signal.SIGKILL)
        process.join(5)
        assert process.exitcode == -signal.SIGKILL
        [remaining] = list_agent_publications("proj", include_quarantined=False)
        assert remaining.logical_key == ("alice.athena.worker", "a" * 40)
        assert remaining.attempts == 0
        with publication_job._publisher_job_lock() as acquired:
            assert acquired
        with bounded_agents_lock(
            lock_path, 0.5, operation="test-reacquire"
        ) as acquired:
            assert acquired
    finally:
        if process.is_alive():
            os.kill(process.pid, signal.SIGKILL)
            process.join(5)
