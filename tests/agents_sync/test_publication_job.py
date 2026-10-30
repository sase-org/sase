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
    global_agent: str,
    revision: str,
    *,
    created_at: float,
    artifacts_dir: Path | str | None = None,
    run_id: str | None = None,
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=global_agent.rsplit(".", 1)[-1],
        global_agent=global_agent,
        primary_revision=revision,
        local_hood="hood",
        artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else None,
        run_id=run_id,
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


def _configure_single_project_job(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
) -> None:
    monkeypatch.setattr(
        publication_job,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj",
                workspace_dir=str(target.primary_checkout),
                is_project=True,
            )
        ],
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
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


def test_publication_hint_can_be_persisted_without_ringing_doorbell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    hints = publication_doorbell.append_publication_hint(
        "proj", _hint("alice.athena.worker", "a" * 40)
    )
    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"

    assert hints.is_file()
    assert not (directory / "doorbell").exists()
    [claim] = publication_doorbell.claim_publication_hints("proj").hints
    assert claim["global_agent"] == "alice.athena.worker"


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
    hinted_key = ("alice.athena.hinted", "b" * 40)

    def drain_selected(_key: str, selected: tuple[tuple[str, str], ...], **_kwargs):
        calls.append("hinted" if hinted_key in selected else "backlog")
        selected_set = set(selected)
        queue[:] = [item for item in queue if item.logical_key not in selected_set]
        return CommitPublicationOutcome(drained=len(selected), published=True)

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", drain_selected
    )
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


def test_retained_link_rows_finish_the_hint_without_ringing_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = _target(tmp_path)
    _configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(publication_job, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    link_agent = "alice.athena.worker"
    hint = _hint(link_agent, "a" * 40)
    hint["link_outbox_agent_name"] = link_agent
    publication_doorbell.ring_publication_doorbell("proj", hint)
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda *_args, **_kwargs: pytest.fail("retained link rows must not re-ring"),
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_machine_artifact_link_store",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        publication_job,
        "drain_artifact_link_outbox",
        lambda **_kwargs: SimpleNamespace(
            drained=1,
            selected_retained=1,
            deferred=False,
        ),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert not tuple(directory.glob("hints.claimed.*"))
    assert "1 artifact-link rows retained for backfill" in str(
        summary.project_stats["proj"]["last_outcome"]
    )


@pytest.mark.parametrize("failure", ["deferred", "raised"])
def test_deferred_or_raised_link_drain_keeps_hint_and_rings_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = _target(tmp_path)
    _configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(publication_job, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        publication_job,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    link_agent = "alice.athena.worker"
    hint = _hint(link_agent, "a" * 40)
    hint["link_outbox_agent_name"] = link_agent
    publication_doorbell.ring_publication_doorbell("proj", hint)
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    monkeypatch.setattr(
        publication_job,
        "resolve_machine_artifact_link_store",
        lambda *_args, **_kwargs: object(),
    )

    def drain_links(**_kwargs: object) -> SimpleNamespace:
        if failure == "raised":
            raise RuntimeError("link store unavailable")
        return SimpleNamespace(drained=0, selected_retained=0, deferred=True)

    monkeypatch.setattr(publication_job, "drain_artifact_link_outbox", drain_links)

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    directory = tmp_path / ".sase" / "projects" / "proj" / "agent_publication"
    assert bells == ["proj"]
    assert tuple(directory.glob("hints.claimed.*"))
    assert summary.project_stats["proj"]["last_outcome"] in {
        "deferred_budget",
        "link_error",
    }


def _referenced_by_item():
    from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem

    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision="a" * 40,
        sidecar_role="plans",
        provider="plan",
        artifact_id="plan:202608/example.md",
        repo_relpath="202608/example.md",
        identity_value=None,
        canonical_ref="plan:202608/example.md",
        destination="https://example.test/prompts/1",
        uses=1,
        published_date="2026-08-12",
    )


def test_publisher_converts_fenced_referenced_by_requests_without_sidecar_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_events, referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = _target(tmp_path)
    _configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: True,
    )
    emitted: list[object] = []
    monkeypatch.setattr(
        referenced_by_events,
        "emit_referenced_by_cites_events",
        lambda items, **_kwargs: emitted.extend(items) or (),
    )
    monkeypatch.setattr(
        referenced_by_publication,
        "_resolve_store",
        lambda *_args, **_kwargs: pytest.fail(
            "fenced conversion must not resolve a store"
        ),
    )
    monkeypatch.setattr(
        referenced_by_publication,
        "refresh_referenced_by",
        lambda *_args, **_kwargs: pytest.fail("fenced conversion must not refresh"),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert emitted == [request]
    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    assert summary.referenced_by_drained == 1
    assert bells == []


def test_publisher_keeps_unfenced_referenced_by_refresh_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )
    from sase.sdd._referenced_by_refresh_models import ReferencedByRefreshReport

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = _target(tmp_path)
    _configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: False,
    )
    monkeypatch.setattr(
        referenced_by_publication, "_resolve_store", lambda _target: object()
    )
    refreshes: list[str] = []
    monkeypatch.setattr(
        referenced_by_publication,
        "refresh_referenced_by",
        lambda _store, *, role, requests, write: (
            refreshes.append(role)
            or ReferencedByRefreshReport(
                root=tmp_path,
                role=role,
                write=write,
                scanned=0,
                actions=(),
                issues=(),
                changed_files=(),
                committed=False,
            )
        ),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert refreshes == ["plans"]
    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    assert summary.referenced_by_drained == 1
    assert request.logical_key not in {
        item.logical_key
        for item in list_referenced_by_requests("proj", include_quarantined=True)
    }


def test_fenced_conversion_failure_quarantines_without_re_ring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync import referenced_by_events, referenced_by_publication
    from sase.agents_sync.referenced_by_outbox import (
        enqueue_referenced_by_request,
        list_referenced_by_requests,
    )

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "1")
    target = _target(tmp_path)
    _configure_single_project_job(monkeypatch, target)
    request = enqueue_referenced_by_request(_referenced_by_item())
    monkeypatch.setattr(
        referenced_by_publication,
        "legacy_referenced_by_writes_fenced",
        lambda _target: True,
    )
    monkeypatch.setattr(
        referenced_by_events,
        "emit_referenced_by_cites_events",
        lambda *_args, **_kwargs: ("event append failed",),
    )
    bells: list[str] = []
    monkeypatch.setattr(
        publication_job,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert list_referenced_by_requests("proj", include_quarantined=False) == ()
    [quarantined] = list_referenced_by_requests("proj", include_quarantined=True)
    assert quarantined.logical_key == request.logical_key
    assert quarantined.attempts == 1
    assert quarantined.quarantined
    assert summary.errors == 1
    assert bells == []


def test_new_publication_waits_for_done_marker_or_ten_minute_grace(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "run"
    item = _item(
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
    item = _item(
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
        _target(tmp_path),
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
