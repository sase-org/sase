"""Bounded, deadline-aware bead projection for artifact-link events."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.sdd import _artifact_link_event_project as project_module
from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd._artifact_link_event_project import (
    BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
    apply_events_to_beads,
)
from sase.sdd.artifact_link_beads import set_bead_endpoint_projections
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.workspace_provider.ownership import WorkspaceOwnershipError
from tests.sdd._artifact_link_acceptance_helpers import (
    PROJECT_KEY,
    _alias_event,
    _baseline_event,
    _cluster,
    _edge_put,
    _edge_remove,
    _read_event,
    _row,
)


def test_tiny_incoming_batch_uses_bounded_bulk_calls_for_historical_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Hot target", IssueType.PLAN)
    historical = tuple(
        _read_event(
            f"{'a' * 24}{index:08x}",
            source="plan:202609/hot.md",
            target=f"bead:{tracked.id}",
        )
        for index in range(40)
    )
    for event in historical:
        _write_event_object(cluster.machine_a.plans, event)
    incoming = _read_event(
        "b" * 32,
        source="plan:202609/hot.md",
        target=f"bead:{tracked.id}",
    )
    captured: list[int] = []

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        captured.append(len(tuple(requests)))
        return set_bead_endpoint_projections(beads_dir, requests)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections", _spy
    )
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 16)

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        (incoming,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 1
    assert report.publication_error is None
    assert captured
    assert all(size <= 16 for size in captured)
    assert sum(captured) == 41
    assert len(captured) == 3
    [link] = cluster.bead_project.show(tracked.id).links
    assert link.uses == 41


def test_deadline_between_chunks_commits_partial_progress_and_retries_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Shared target", IssueType.PLAN)
    events = tuple(
        _read_event(
            f"{'c' * 24}{index:08x}",
            source="plan:202609/hot.md",
            target=f"bead:{tracked.id}",
        )
        for index in range(3)
    )
    for event in events:
        _write_event_object(cluster.machine_a.plans, event)
    objects = tuple(canonical_artifact_link_event_object(event) for event in events)
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 1)
    calls = 0
    now = [0.0]
    monkeypatch.setattr(project_module.time, "monotonic", lambda: now[0])

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        outcome = set_bead_endpoint_projections(beads_dir, requests)
        now[0] = 10.0
        return outcome

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections", _spy
    )

    first = apply_events_to_beads(
        cluster.machine_a.store,
        objects,
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
        deadline=5.0,
    )

    assert calls == 1
    assert first.changed is True
    assert first.receipt is False
    assert first.deferred is True
    assert first.diagnostic == BEAD_PROJECTION_DEFERRED_DIAGNOSTIC
    [partial] = cluster.bead_project.show(tracked.id).links
    assert partial.uses == 3

    now[0] = 0.0
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 64)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        set_bead_endpoint_projections,
    )
    retry = apply_events_to_beads(
        cluster.machine_a.store,
        objects,
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
    )
    stable = apply_events_to_beads(
        cluster.machine_a.store,
        objects,
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
    )

    assert retry.receipt is True
    assert stable.receipt is True
    assert stable.changed is False
    [link] = cluster.bead_project.show(tracked.id).links
    assert link.uses == 3


def test_outbox_deadline_retains_operations_then_retry_acks_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Queued target", IssueType.PLAN)
    events = tuple(
        _edge_put(
            f"{'d' * 24}{index:08x}",
            source="plan:202609/hot.md",
            relation="implements",
            target=f"bead:{tracked.id}",
            description="derived from the plan's `bead_id:` frontmatter field",
            origin="derived",
        )
        for index in range(3)
    )
    for event in events:
        append_artifact_link_outbox_event(
            project_key=PROJECT_KEY,
            agent_name="machine",
            run_id="budget",
            event=event,
        )
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 1)
    now = [0.0]
    monkeypatch.setattr(project_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        "sase.sdd._artifact_link_outbox_drain.time.monotonic", lambda: now[0]
    )
    monkeypatch.setattr(
        "sase.sdd._artifact_link_event_publish.time.monotonic", lambda: now[0]
    )

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        outcome = set_bead_endpoint_projections(beads_dir, requests)
        now[0] = 10.0
        return outcome

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections", _spy
    )

    first = drain_artifact_link_outbox(
        store=cluster.machine_a.store,
        agent_name="machine",
        drop_stale_terminal=False,
        push_after_commit=False,
        deadline=5.0,
    )

    assert first.deferred is True
    assert first.drained == 0
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 3

    now[0] = 0.0
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 64)
    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        set_bead_endpoint_projections,
    )
    retry = drain_artifact_link_outbox(
        store=cluster.machine_a.store,
        agent_name="machine",
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    idle = drain_artifact_link_outbox(
        store=cluster.machine_a.store,
        agent_name="machine",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert retry.drained == 3
    assert retry.deferred is False
    assert idle.drained == 0
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    [link] = cluster.bead_project.show(tracked.id).links
    assert link.uses == 1
    assert link.relation == "implements"


def test_alias_remove_and_baseline_scope_indirect_bead_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Scoped target", IssueType.PLAN)
    other = cluster.bead_project.create("Unrelated", IssueType.PLAN)
    historical = _edge_put(
        "e" * 32,
        source="plan:202609/renamed_old.md",
        relation="implements",
        target=f"bead:{tracked.id}",
        description="derived from the plan's `bead_id:` frontmatter field",
        origin="derived",
    )
    unrelated = _edge_put(
        "f" * 32,
        source="plan:202609/hot.md",
        relation="implements",
        target=f"bead:{other.id}",
        description="unrelated historical edge",
        origin="derived",
    )
    publish_artifact_link_events(
        cluster.machine_a.store,
        (historical, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    captured: list[tuple[str, str]] = []

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        captured.extend(
            (str(request["issue_id"]), str(request["target_ref"]))
            for request in requests
        )
        return set_bead_endpoint_projections(beads_dir, requests)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections", _spy
    )

    alias_report = publish_artifact_link_events(
        cluster.machine_a.store,
        (
            _alias_event(
                "1" * 32,
                old_ref="plan:202609/renamed_old.md",
                new_ref="plan:202609/renamed_new.md",
            ),
        ),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert alias_report.published == 1
    assert (other.id, "plan:202609/hot.md") not in captured
    assert any(
        issue_id == tracked.id
        and target in {"plan:202609/renamed_old.md", "plan:202609/renamed_new.md"}
        for issue_id, target in captured
    )

    captured.clear()
    remove_report = publish_artifact_link_events(
        cluster.machine_a.store,
        (
            _edge_remove(
                "2" * 32,
                source="plan:202609/renamed_new.md",
                relation="implements",
                target=f"bead:{tracked.id}",
                observed=("e" * 32,),
            ),
        ),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert remove_report.published == 1
    assert all(issue_id == tracked.id for issue_id, _target in captured)
    assert (other.id, "plan:202609/hot.md") not in captured

    captured.clear()
    first = _row(
        source="plan:202609/baseline-a.md",
        relation="implements",
        target=f"bead:{tracked.id}",
        origin="migrated",
        description="first imported edge",
        created_by="agent:importer.athena.worker",
        created_at="2026-09-10T00:00:00Z",
    )
    second = _row(
        source="plan:202609/baseline-b.md",
        relation="implements",
        target=f"bead:{tracked.id}",
        origin="migrated",
        description="second imported edge",
        created_by="agent:importer.athena.worker",
        created_at="2026-09-10T00:00:00Z",
    )
    baseline_report = publish_artifact_link_events(
        cluster.machine_a.store,
        (_baseline_event("3" * 32, (first, second)),),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert baseline_report.published == 1
    assert {target for issue_id, target in captured if issue_id == tracked.id} >= {
        "plan:202609/baseline-a.md",
        "plan:202609/baseline-b.md",
    }
    assert (other.id, "plan:202609/hot.md") not in captured


def test_authorization_runs_before_the_first_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Unauthorized", IssueType.PLAN)
    event = _edge_put(
        "4" * 32,
        source="plan:202609/hot.md",
        relation="implements",
        target=f"bead:{tracked.id}",
        description="derived from the plan's `bead_id:` frontmatter field",
        origin="derived",
    )
    item = canonical_artifact_link_event_object(event)
    before = _file_snapshot(cluster.bead_project.beads_dir)

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise WorkspaceOwnershipError("machine mutation refused at test beads root")

    monkeypatch.setattr(
        "sase.workspace_provider.ownership.authorize_store_mutation",
        _refuse,
    )

    def _must_not_batch(*_args: object, **_kwargs: object) -> dict[str, object]:
        pytest.fail("batch must not run before authorization")

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _must_not_batch,
    )

    projection = apply_events_to_beads(
        cluster.machine_a.store,
        (item,),
        mutation_origin="machine",
        artifacts_dir=None,
    )

    assert projection.changed is False
    assert projection.receipt is False
    assert projection.diagnostic is not None
    assert "machine mutation refused" in projection.diagnostic
    assert _file_snapshot(cluster.bead_project.beads_dir) == before


def test_hard_publication_failure_is_not_a_deadline_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    tracked = cluster.bead_project.create("Broken", IssueType.PLAN)
    event = _edge_put(
        "5" * 32,
        source="plan:202609/hot.md",
        relation="implements",
        target=f"bead:{tracked.id}",
        description="derived from the plan's `bead_id:` frontmatter field",
        origin="derived",
    )

    def _boom(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("projection exploded")

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _boom,
    )

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 0
    assert report.deferred is False
    assert any("projection exploded" in item for item in report.skip_diagnostics)


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_event_object(root: Path, event: dict[str, object]) -> Path:
    item = canonical_artifact_link_event_object(event)
    path = root / item.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(item.payload)
    return path
