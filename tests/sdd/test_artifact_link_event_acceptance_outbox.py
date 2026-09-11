"""Acceptance coverage for artifact-link event outbox recovery."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from sase.bead._sync_publication import PushOutcome
from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_outbox_io import (
    inspect_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.sdd._artifact_link_publication_retry import (
    sweep_artifact_link_publication_retries,
)
from sase.sdd._artifact_link_publication_retry_state import (
    artifact_link_publication_state_path,
)
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from tests.sdd._artifact_link_acceptance_helpers import (
    PROJECT_KEY,
    _cluster,
    _git_status,
    _head_payload,
    _machine_root,
    _read_event,
    _remote_event_operation_ids,
    _unmerged_files,
    _uses,
)


def test_outbox_crash_recovery_retirement_and_retry_ledger_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover after event-write, commit, and publish-boundary interruptions."""

    cluster = _cluster(tmp_path, monkeypatch)
    machine = cluster.machine_a
    event_after_write = _read_event(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaa1111",
        source="agent:crash-write.athena.worker",
        target="plan:202609/hot.md",
    )
    event_object = canonical_artifact_link_event_object(event_after_write)
    partial_path = machine.plans / event_object.relative_path
    partial_path.parent.mkdir(parents=True)
    partial_path.write_bytes(event_object.payload)

    recovered_write = publish_artifact_link_events(
        machine.store,
        (event_after_write,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert recovered_write.published_operation_ids == (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaa1111",
    )
    assert recovered_write.committed is True
    assert _head_payload(machine.plans, event_object.relative_path) == (
        event_object.payload
    )

    event_after_commit = _read_event(
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbb1111",
        source="agent:crash-commit.athena.worker",
        target="plan:202609/hot.md",
    )
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="boundary",
        event=event_after_commit,
        now=10.0,
    )
    committed_once = publish_artifact_link_events(
        machine.store,
        (event_after_commit,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert committed_once.published == 1
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 1
    record_artifact_link_release_evidence(
        project_key=PROJECT_KEY,
        run_id="boundary",
        agent_id="machine",
        qualifying_repo_ids=(str(machine.plans),),
    )

    drained = drain_artifact_link_outbox(
        store=machine.store,
        agent_name="machine",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert drained.drained == 1
    assert drained.committed is False
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert (
        _uses(
            machine.store.load_aggregate()["rows"],
            "agent:crash-commit.athena.worker",
            "read",
            "plan:202609/hot.md",
        )
        == 1
    )

    queued = _read_event(
        "cccccccccccccccccccccccccccc1111",
        source="agent:queue-age.athena.worker",
        target="plan:202609/hot.md",
    )
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="age",
        event=queued,
        now=100.0,
    )
    stats = inspect_artifact_link_outbox(PROJECT_KEY, now=250.0)
    assert stats.event_queued == 1
    assert stats.p95_age_seconds == 150.0

    pushed_before = _remote_event_operation_ids(cluster.plans_remote)
    transient_failure = _read_event(
        "dddddddddddddddddddddddddddd1111",
        source="agent:ledger.athena.worker",
        target="plan:202609/hot.md",
    )

    def _reject_push(
        _repo_root: Path,
        *,
        worker_lock_wait: float = 0.0,
        deadline: float | None = None,
    ) -> PushOutcome:
        return PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="simulated publication crash after commit",
        )

    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", _reject_push)
        failed_publish = publish_artifact_link_events(
            machine.store,
            (transient_failure,),
            push_after_commit=True,
            mutation_origin="machine",
        )

    assert failed_publish.published_operation_ids == (
        "dddddddddddddddddddddddddddd1111",
    )
    assert failed_publish.publication_error is not None
    assert "Scheduled artifact_link_backfill will retry" in (
        failed_publish.publication_error
    )
    assert _remote_event_operation_ids(cluster.plans_remote) == pushed_before
    assert artifact_link_publication_state_path(PROJECT_KEY).is_file()

    retry_roots = (
        _machine_root(
            role="plans",
            repo_root=machine.plans,
            remote_url=cluster.plans_remote,
        ),
    )
    sweep = sweep_artifact_link_publication_retries(
        retry_roots,
        now=time.time() + 3_700.0,
        deadline=time.monotonic() + 60.0,
        worker_lock_wait=1.0,
    )

    assert sweep.attempted == 1
    assert sweep.published == 1
    assert sweep.failed == 0
    assert "dddddddddddddddddddddddddddd1111" in _remote_event_operation_ids(
        cluster.plans_remote
    )
    assert _git_status(machine.plans) == ""
    assert _unmerged_files(machine.plans) == ()
