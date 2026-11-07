"""Parked-ledger drain, requeue, and compact-read tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.sdd._artifact_link_outbox_drain import drain_artifact_link_outbox
from sase.sdd._artifact_link_outbox_io import (
    read_artifact_link_outbox_entries,
    rewrite_artifact_link_outbox_without_ids,
)
from sase.sdd._artifact_link_outbox_parked import (
    PARKED_RECHECK_SECONDS,
    append_artifact_link_parked_entries,
    artifact_link_outbox_parked_path,
    inspect_artifact_link_parked,
    parked_entry_from_outbox,
    read_artifact_link_parked_entries,
)
from sase.sdd.artifact_link_backfill import run_artifact_link_backfill_batch
from sase.sdd.artifact_link_beads import set_bead_endpoint_projections
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_event
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_acceptance_helpers import (
    PROJECT_KEY,
    _cluster,
    _edge_put,
    _mixed_cluster,
)


def _put(operation_id: str, *, target: str) -> dict[str, object]:
    return _edge_put(
        operation_id,
        source="plan:202609/hot.md",
        relation="implements",
        target=target,
        description="derived from the plan's `bead_id:` frontmatter field",
        origin="derived",
    )


def _queue(store: ArtifactLinkStore, event: dict[str, object]) -> None:
    append_artifact_link_outbox_event(
        project_key=store.project_key,
        agent_name="machine",
        run_id="parked-drain",
        event=event,
    )


def _sync_drain(store: ArtifactLinkStore, **kwargs: object) -> object:
    kwargs.setdefault("drop_stale_terminal", False)
    kwargs.setdefault("push_after_commit", False)
    return drain_artifact_link_outbox(store=store, **kwargs)  # type: ignore[arg-type]


def test_drain_parks_mixed_endpoints_and_second_tick_skips_recheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = _mixed_cluster(tmp_path, monkeypatch)
    cluster = mixed.cluster
    local = cluster.bead_project.create("Keep", IssueType.PLAN)
    removed = cluster.bead_project.create("Gone", IssueType.PLAN)
    cluster.bead_project.remove(removed.id)
    events = (
        _put("b" * 32, target=f"bead:{local.id}"),
        _put("c" * 32, target=f"bead:{mixed.foreign_issue_id}"),
        _put("d" * 32, target=f"bead:{removed.id}"),
        _put("e" * 32, target="bead:sase-164"),
    )
    for event in events:
        _queue(cluster.machine_a.store, event)
    projection_calls = 0
    real = set_bead_endpoint_projections

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        nonlocal projection_calls
        projection_calls += 1
        return real(beads_dir, requests)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _spy,
    )

    first = _sync_drain(cluster.machine_a.store)
    parked = read_artifact_link_parked_entries(PROJECT_KEY)
    checked_at = tuple(item.last_checked_at for item in parked)

    assert first.drained == 1
    assert first.parked_new == 3
    assert first.parked_total == 3
    assert first.bead_projection_failed == 0
    assert {item.operation_id for item in first.parked_details} == {
        "c" * 32,
        "d" * 32,
        "e" * 32,
    }
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert projection_calls >= 1
    first_calls = projection_calls

    second = _sync_drain(cluster.machine_a.store)

    assert second.drained == 0
    assert second.parked_new == 0
    assert second.parked_total == 3
    assert projection_calls == first_calls
    replay = read_artifact_link_parked_entries(PROJECT_KEY)
    assert tuple(item.last_checked_at for item in replay) == checked_at


def test_requeue_after_local_bead_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    local = cluster.bead_project.create("Now local", IssueType.PLAN)
    ready = _put("a" * 32, target=f"bead:{local.id}")
    queued = append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="parked-drain",
        event=ready,
    )
    rewrite_artifact_link_outbox_without_ids(
        PROJECT_KEY, drained_ids={queued.id}, dropped=[]
    )
    append_artifact_link_parked_entries(
        PROJECT_KEY,
        (
            parked_entry_from_outbox(
                queued,
                reasons=("outcome absent",),
                now=1.0,
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_parked.PARKED_RECHECK_SECONDS",
        0,
    )

    replay = _sync_drain(cluster.machine_a.store, now=10.0)

    assert replay.drained == 1
    assert replay.parked_total == 0
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert read_artifact_link_parked_entries(PROJECT_KEY) == ()
    [link] = cluster.bead_project.show(local.id).links
    assert link.target_ref == "plan:202609/hot.md"


def test_parked_read_compacts_duplicate_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    event = _put("e" * 32, target="bead:sase-164")
    queued = append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="parked-drain",
        event=event,
    )
    rewrite_artifact_link_outbox_without_ids(
        PROJECT_KEY, drained_ids={queued.id}, dropped=[]
    )
    append_artifact_link_parked_entries(
        PROJECT_KEY,
        (parked_entry_from_outbox(queued, reasons=("outcome absent",)),),
    )
    path = artifact_link_outbox_parked_path(PROJECT_KEY)
    [line] = path.read_text(encoding="utf-8").splitlines()
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    entries = read_artifact_link_parked_entries(PROJECT_KEY)
    stats = inspect_artifact_link_parked(PROJECT_KEY)

    assert len(entries) == 1
    assert stats.parked == 1


def test_sweep_marks_parked_documents_swept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = _mixed_cluster(tmp_path, monkeypatch)
    cluster = mixed.cluster
    plan = cluster.machine_a.plans / "202609" / "foreign.md"
    plan.write_text(
        f"---\ntier: tale\nbead_id: {mixed.foreign_issue_id}\n---\n\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation._known_bead_ids",
        lambda _store: frozenset({mixed.foreign_issue_id}),
    )
    real_drain = drain_artifact_link_outbox

    def _drain(*args: object, **kwargs: object):
        kwargs["push_after_commit"] = False
        return real_drain(*args, **kwargs)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        _drain,
    )

    report, swept = run_artifact_link_backfill_batch(
        cluster.machine_a.store,
        already_swept=frozenset(),
        batch_size=500,
    )

    assert report.remaining == 0
    assert "plan:202609/foreign.md" in swept
    assert inspect_artifact_link_parked(PROJECT_KEY).parked >= 1


def test_parked_recheck_constant_is_one_day() -> None:
    assert PARKED_RECHECK_SECONDS == 24 * 60 * 60


def _park(operation_id: str, *, parked_at: float) -> None:
    queued = append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="parked-drain",
        event=_put(operation_id, target="bead:sase-164"),
    )
    rewrite_artifact_link_outbox_without_ids(
        PROJECT_KEY, drained_ids={queued.id}, dropped=[]
    )
    append_artifact_link_parked_entries(
        PROJECT_KEY,
        (parked_entry_from_outbox(queued, reasons=("outcome absent",), now=parked_at),),
    )


def test_parked_recheck_persists_last_checked_and_throttles_the_next_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={})
    _park("a" * 32, parked_at=1.0)
    checks = 0

    def _not_local(_store: object, _entry: object) -> bool:
        nonlocal checks
        checks += 1
        return False

    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain._parked_endpoints_are_local",
        _not_local,
    )
    first_now = 1.0 + PARKED_RECHECK_SECONDS + 5.0

    _sync_drain(store, now=first_now)

    assert checks == 1
    [item] = read_artifact_link_parked_entries(PROJECT_KEY)
    assert item.last_checked_at == first_now
    assert item.parked_at == 1.0

    _sync_drain(store, now=first_now + 60.0)

    assert checks == 1
    [item] = read_artifact_link_parked_entries(PROJECT_KEY)
    assert item.last_checked_at == first_now


def test_parked_recheck_keeps_an_entry_parked_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={})
    _park("a" * 32, parked_at=1.0)
    now = 1.0 + PARKED_RECHECK_SECONDS + 5.0

    def _park_another_then_not_local(_store: object, _entry: object) -> bool:
        # Another drain parks a new operation while this recheck is running.
        _park("b" * 32, parked_at=now)
        return False

    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain._parked_endpoints_are_local",
        _park_another_then_not_local,
    )

    _sync_drain(store, now=now)

    parked = {
        item.entry.id: item for item in read_artifact_link_parked_entries(PROJECT_KEY)
    }
    assert set(parked) == {"a" * 32, "b" * 32}
    assert parked["a" * 32].last_checked_at == now
