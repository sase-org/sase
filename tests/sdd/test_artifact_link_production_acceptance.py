"""Scaled production-path proof for artifact-link bead projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.core import bead_mutation_facade as rust_beads
from sase.sdd import _artifact_link_event_project as project_module
from sase.sdd import artifact_link_backfill as backfill_module
from sase.sdd import artifact_link_derivation as derivation_module
from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd._artifact_link_event_project import (
    BEAD_PROJECTION_BATCH_SIZE,
    BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    apply_events_to_beads,
)
from sase.sdd.artifact_link_backfill import run_artifact_link_backfill_batch
from sase.sdd.artifact_link_beads import set_bead_endpoint_projections
from sase.sdd.artifact_link_outbox import read_artifact_link_outbox_entries
from tests.sdd._artifact_link_acceptance_helpers import (
    PROJECT_KEY,
    _cluster,
    _edge_put,
    _git_status,
)
from tests.sdd_store._helpers import commit_all

_HISTORICAL_RECEIPTS = 80
_SCALED_PLAN = "202609/scaled.md"
_SCALED_REF = f"plan:{_SCALED_PLAN}"
_SEED_REFS = frozenset(
    {
        "plan:202609/hot.md",
        "plan:202609/renamed_new.md",
        "plan:202609/source.md",
        "research:202609/source.md",
    }
)


def test_scaled_backfill_bounds_bulk_io_defers_then_converges_without_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the old per-receipt load/save path and prove the batch bound."""

    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Scaled target", IssueType.PLAN)
    _write_scaled_plan(cluster.machine_a.plans, bead_id=tracked.id)
    historical = tuple(
        _edge_put(
            f"{'a' * 24}{index:08x}",
            source=_SCALED_REF,
            relation="implements",
            target=f"bead:{tracked.id}",
            description="derived from the plan's `bead_id:` frontmatter field",
            origin="derived",
        )
        for index in range(_HISTORICAL_RECEIPTS)
    )
    for event in historical:
        _write_event_object(cluster.machine_a.plans, event)
    commit_all(cluster.machine_a.plans, "seed historical bead-link receipts")

    bulk_sizes: list[int] = []
    core_sizes: list[int] = []
    core_changed: list[bool] = []
    now = [0.0]
    real_bulk = set_bead_endpoint_projections
    real_core = rust_beads.set_link_projections

    def _spy_bulk(beads_dir: Path, requests: object) -> dict[str, object]:
        payload = tuple(requests)
        bulk_sizes.append(len(payload))
        outcome = real_bulk(beads_dir, payload)
        now[0] = 10.0
        return outcome

    def _spy_core(beads_dir: Path, requests: object) -> dict[str, object]:
        payload = tuple(requests)
        core_sizes.append(len(payload))
        outcome = real_core(beads_dir, payload)
        core_changed.append(bool(outcome.get("changed")))
        return outcome

    _patch_monotonic(monkeypatch, now)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _spy_bulk,
    )
    monkeypatch.setattr(
        "sase.core.bead_mutation_facade.set_link_projections",
        _spy_core,
    )

    first_report, first_swept = run_artifact_link_backfill_batch(
        cluster.machine_a.store,
        already_swept=_SEED_REFS,
        batch_size=8,
        deadline=20.0,
        persist_deadline=5.0,
    )

    expected_requests = _HISTORICAL_RECEIPTS + 1
    expected_batches = (
        expected_requests + BEAD_PROJECTION_BATCH_SIZE - 1
    ) // BEAD_PROJECTION_BATCH_SIZE
    assert BEAD_PROJECTION_BATCH_SIZE == 64
    assert expected_batches == 2
    assert first_report.candidates == 1
    assert first_report.errors
    assert any(
        BEAD_PROJECTION_DEFERRED_DIAGNOSTIC in item for item in first_report.errors
    )
    assert _SCALED_REF not in first_swept
    assert read_artifact_link_outbox_entries(PROJECT_KEY)
    assert bulk_sizes == [BEAD_PROJECTION_BATCH_SIZE]
    assert core_sizes == [BEAD_PROJECTION_BATCH_SIZE]
    assert core_changed == [True]
    [partial] = cluster.bead_project.show(tracked.id).links
    assert partial.relation == "implements"
    assert partial.target_ref == _SCALED_REF
    assert partial.origin == "derived"
    assert partial.uses == 1

    now[0] = 0.0
    bulk_sizes.clear()
    core_sizes.clear()
    core_changed.clear()
    retry_report, retry_swept = run_artifact_link_backfill_batch(
        cluster.machine_a.store,
        already_swept=first_swept,
        batch_size=8,
    )

    assert retry_report.errors == ()
    assert _SCALED_REF in retry_swept
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert bulk_sizes
    assert core_sizes == bulk_sizes
    assert all(size <= BEAD_PROJECTION_BATCH_SIZE for size in bulk_sizes)
    assert sum(bulk_sizes) == expected_requests
    assert len(bulk_sizes) == expected_batches
    [link] = cluster.bead_project.show(tracked.id).links
    assert link.uses == 1
    assert link.relation == "implements"
    assert link.origin == "derived"
    assert _git_status(cluster.machine_a.plans) == ""

    snapshot = _file_snapshot(cluster.bead_project.beads_dir)
    now[0] = 0.0
    bulk_sizes.clear()
    core_sizes.clear()
    core_changed.clear()
    replay = apply_events_to_beads(
        cluster.machine_a.store,
        (),
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
    )

    assert replay.receipt is True
    assert replay.changed is False
    assert replay.deferred is False
    assert all(changed is False for changed in core_changed)
    assert _file_snapshot(cluster.bead_project.beads_dir) == snapshot
    assert _git_status(cluster.machine_a.plans) == ""


def _write_scaled_plan(plans: Path, *, bead_id: str) -> None:
    path = plans / _SCALED_PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: tale\nbead_id: {bead_id}\n---\n\nscaled fixture\n",
        encoding="utf-8",
    )
    commit_all(plans, "add scaled production-acceptance plan")


def _write_event_object(root: Path, event: dict[str, object]) -> Path:
    item = canonical_artifact_link_event_object(event)
    path = root / item.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(item.payload)
    return path


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _patch_monotonic(monkeypatch: pytest.MonkeyPatch, now: list[float]) -> None:
    def clock() -> float:
        return now[0]

    monkeypatch.setattr(project_module.time, "monotonic", clock)
    monkeypatch.setattr(backfill_module.time, "monotonic", clock)
    monkeypatch.setattr(derivation_module.time, "monotonic", clock)
    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain.time.monotonic",
        clock,
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_event_publish.time.monotonic",
        clock,
    )
