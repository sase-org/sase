"""Tests for the host-owned publication doorbell and drain job."""

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
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from tests._conftest_environment import redirect_sase_home


def _item(
    global_agent: str, revision: str, *, created_at: float
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=global_agent.rsplit(".", 1)[-1],
        global_agent=global_agent,
        primary_revision=revision,
        local_hood="hood",
        created_at=created_at,
    )


def _target(tmp_path: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=tmp_path / "primary",
        primary_roots=(tmp_path / "primary",),
        sidecar_path=tmp_path / "agents",
        remote_url="https://example.invalid/agents.git",
    )


def _hint(global_agent: str, revision: str) -> dict[str, str]:
    return {
        "local_agent": "worker",
        "global_agent": global_agent,
        "primary_revision": revision,
        "run_id": "run-1",
        "link_outbox_agent_name": "",
    }


def test_doorbell_hint_claim_recovers_after_interrupted_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    first = publication_doorbell.ring_publication_doorbell(
        "proj", _hint("alice.athena.worker", "a" * 40)
    )
    first_claim = publication_doorbell.claim_publication_hints("proj")
    assert first.is_file()
    assert len(first_claim.hints) == 1
    assert first_claim.hints[0]["global_agent"] == "alice.athena.worker"
    assert first_claim.paths and first_claim.paths[0].is_file()

    # Simulate a crash: leave the claim untouched and append a new hint.
    publication_doorbell.ring_publication_doorbell(
        "proj", _hint("alice.athena.other", "b" * 40)
    )
    recovered = publication_doorbell.claim_publication_hints("proj")
    assert {hint["global_agent"] for hint in recovered.hints} == {
        "alice.athena.worker",
        "alice.athena.other",
    }
    publication_doorbell.finish_hint_claim(recovered)
    claimed_dir = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert not tuple(claimed_dir.glob("hints.claimed.*"))


def test_heartbeat_round_trip_and_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    now = time.time()
    path = publication_doorbell.write_publication_heartbeat(
        {
            "proj": {
                "active_count": 2,
                "oldest_active_age_seconds": 8.5,
                "last_outcome": "drained",
            }
        },
        now=now,
    )
    payload = publication_doorbell._read_publication_heartbeat()
    assert path.is_file()
    assert payload is not None
    assert payload["projects"]["proj"]["active_count"] == 2
    assert publication_doorbell.publisher_is_live(60)

    publication_doorbell.write_publication_heartbeat({}, now=now - 61)
    assert not publication_doorbell.publisher_is_live(60)


def test_hinted_hood_requests_are_drained_before_the_oldest_backlog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    queue = [
        _item("alice.athena.backlog", "a" * 40, created_at=1),
        _item("alice.athena.hinted", "b" * 40, created_at=2),
    ]
    monkeypatch.setattr(
        publication_job, "active_agent_publications", lambda _key: tuple(queue)
    )
    monkeypatch.setattr(
        publication_job, "list_referenced_by_requests", lambda *_args, **_kwargs: ()
    )
    calls: list[str] = []

    def drain_selected(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.append("hinted")
        selected_set = set(selected)
        queue[:] = [item for item in queue if item.logical_key not in selected_set]
        return CommitPublicationOutcome(drained=len(selected), published=True)

    def drain_oldest(_key: str, **_kwargs):
        calls.append("backlog")
        queue.pop(0)
        return CommitPublicationOutcome(drained=1, published=True)

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_selected
    )
    monkeypatch.setattr(publication_queue, "drain_agent_publications", drain_oldest)
    publication_doorbell.ring_publication_doorbell(
        "proj", _hint("alice.athena.hinted", "b" * 40)
    )

    outcome = publication_job._drain_project(
        _target(tmp_path),
        deadline=time.monotonic() + 10,
        git_runner=lambda *_a, **_k: None,  # type: ignore[arg-type]
    )

    assert calls == ["hinted", "backlog"]
    assert outcome.hood_drained == 2
    assert queue == []


def test_busy_agents_lock_rings_again_without_charging_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    item = _item("alice.athena.worker", "a" * 40, created_at=1)
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
    target = _target(tmp_path)
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
        "proj", _hint("alice.athena.worker", "a" * 40)
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
    item = _item("alice.athena.worker", "a" * 40, created_at=1)
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
        lambda _keys: SimpleNamespace(targets=(_target(tmp_path),), outcomes=()),
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
    enqueue_agent_publication(_item("alice.athena.worker", "a" * 40, created_at=1))
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
