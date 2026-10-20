"""Per-operation bead endpoint classification and skip-mode projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.sdd import _artifact_link_event_project as project_module
from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd._artifact_link_event_ownership import publication_evidence
from sase.sdd._artifact_link_event_project import apply_events_to_beads
from sase.sdd.artifact_link_beads import set_bead_endpoint_projections
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from tests.sdd._artifact_link_acceptance_helpers import (
    _edge_put,
    _mixed_cluster,
)


def _put(
    operation_id: str,
    *,
    target: str,
) -> dict[str, object]:
    return _edge_put(
        operation_id,
        source="plan:202609/hot.md",
        relation="implements",
        target=target,
        description="derived from the plan's `bead_id:` frontmatter field",
        origin="derived",
    )


def test_local_endpoint_is_committed_and_acknowledged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = _mixed_cluster(tmp_path, monkeypatch)
    cluster = mixed.cluster
    tracked = cluster.bead_project.create("Local target", IssueType.PLAN)
    event = _put("a" * 32, target=f"bead:{tracked.id}")
    captured: list[dict[str, object]] = []
    real = set_bead_endpoint_projections

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        payload = [dict(request) for request in tuple(requests)]
        captured.extend(payload)
        return real(beads_dir, payload)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _spy,
    )

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert captured
    assert all(request.get("missing_holder") == "skip" for request in captured)
    assert report.published == 1
    assert report.published_operation_ids == ("a" * 32,)
    [link] = cluster.bead_project.show(tracked.id).links
    assert link.target_ref == "plan:202609/hot.md"
    replay = publish_artifact_link_events(
        cluster.machine_a.store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert replay.published == 1
    assert replay.beads_changed is False


def test_foreign_removed_and_absent_endpoints_are_parked_with_typed_reasons(
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

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        events,
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published_operation_ids == ("b" * 32,)
    parked_by_id = {item.operation_id: item for item in report.parked_operations}
    assert set(parked_by_id) == {"c" * 32, "d" * 32, "e" * 32}
    assert any("foreign" in reason for reason in parked_by_id["c" * 32].reasons)
    assert any("bob-cli" in reason for reason in parked_by_id["c" * 32].reasons)
    assert any("removed" in reason for reason in parked_by_id["d" * 32].reasons)
    assert any("absent" in reason for reason in parked_by_id["e" * 32].reasons)
    assert any("bead:sase-164" in reason for reason in parked_by_id["e" * 32].reasons)
    [link] = cluster.bead_project.show(local.id).links
    assert link.target_ref == "plan:202609/hot.md"
    replay = apply_events_to_beads(
        cluster.machine_a.store,
        tuple(canonical_artifact_link_event_object(event) for event in events),
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
    )
    assert replay.receipt is True
    assert replay.changed is False


def test_transient_endpoint_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = _mixed_cluster(tmp_path, monkeypatch)
    cluster = mixed.cluster
    event = _put("f" * 32, target=f"bead:{mixed.unavailable_issue_id}")

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 0
    assert report.deferred is False
    assert any("transient" in item for item in report.skip_diagnostics)
    assert any(mixed.unavailable_issue_id in item for item in report.skip_diagnostics)


def test_exception_in_second_chunk_commits_first_and_leaves_no_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mixed = _mixed_cluster(tmp_path, monkeypatch)
    cluster = mixed.cluster
    first = cluster.bead_project.create("Chunk one", IssueType.PLAN)
    second = cluster.bead_project.create("Chunk two", IssueType.PLAN)
    events = (
        _put("1" * 32, target=f"bead:{first.id}"),
        _put("2" * 32, target=f"bead:{second.id}"),
    )
    objects = tuple(canonical_artifact_link_event_object(event) for event in events)
    monkeypatch.setattr(project_module, "BEAD_PROJECTION_BATCH_SIZE", 1)
    calls = 0
    real = set_bead_endpoint_projections

    def _spy(beads_dir: Path, requests: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("chunk 2 exploded")
        return real(beads_dir, requests)

    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        _spy,
    )

    report = publish_artifact_link_events(
        cluster.machine_a.store,
        events,
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert calls == 2
    assert report.published == 1
    assert report.deferred is False
    assert report.bead_projection_failed is True
    assert any("chunk 2 exploded" in item for item in report.skip_diagnostics)
    assert (
        project_module._bead_store_has_uncommitted_changes(
            cluster.bead_project.beads_dir
        )
        is False
    )
    linked = [
        issue
        for issue in (
            cluster.bead_project.show(first.id),
            cluster.bead_project.show(second.id),
        )
        if issue.links
    ]
    assert len(linked) == 1
    monkeypatch.setattr(
        "sase.sdd.artifact_link_beads.set_bead_endpoint_projections",
        real,
    )
    retry = apply_events_to_beads(
        cluster.machine_a.store,
        objects,
        mutation_origin="machine",
        artifacts_dir=None,
        force=True,
    )
    assert retry.receipt is True
    assert cluster.bead_project.show(first.id).links
    assert cluster.bead_project.show(second.id).links


def test_publication_evidence_includes_per_endpoint_outcomes() -> None:
    payload = publication_evidence(
        operation_id="a" * 32,
        resolved_roots={},
        forced_roots=(),
        durable_roots=(),
        bead_owner=True,
        bead_receipt=False,
        local_receipt=True,
        bead_endpoints=(
            {
                "endpoint_ref": "bead:sase-102",
                "outcome": {"foreign": {"owner_project": "bob-cli"}},
            },
        ),
    )

    assert payload["bead_endpoints"] == [
        {
            "endpoint_ref": "bead:sase-102",
            "outcome": {"foreign": {"owner_project": "bob-cli"}},
        }
    ]
    omitted = publication_evidence(
        operation_id="a" * 32,
        resolved_roots={},
        forced_roots=(),
        durable_roots=(),
        bead_owner=True,
        bead_receipt=False,
        local_receipt=True,
    )
    assert "bead_endpoints" not in omitted
