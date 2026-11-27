"""Ownerless and bead-only local receipt publication tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_event_local_store import artifact_link_local_event_root
from sase.sdd.artifact_link_event_publisher import (
    active_operation_ids_for_row,
    observation_or_put_event_from_row,
    publish_artifact_link_events,
    rows_from_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def test_publish_ownerless_event_gets_machine_local_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="agent:reader",
            relation="related",
            target="agent:planner",
            origin="manual",
        ),
        project_key=store.project_key,
        operation_id="dddddddddddddddddddddddddddddddd",
    )
    event_object = canonical_artifact_link_event_object(event)
    local_root = artifact_link_local_event_root(store.project_key)

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published_operation_ids == ("dddddddddddddddddddddddddddddddd",)
    assert report.published == 1
    assert (
        local_root / event_object.relative_path
    ).read_bytes() == event_object.payload
    assert (local_root / event_object.relative_path) in report.durable_event_paths
    [row] = store.load_aggregate()["rows"]
    assert {row["source_ref"], row["target_ref"]} == {
        "agent:reader",
        "agent:planner",
    }


def test_publish_bead_only_events_get_local_history_before_bead_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    with BeadProject.init(tmp_path / "beads") as project:
        issue = project.create("Read target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=project.beads_dir,
        )
        events = tuple(
            observation_or_put_event_from_row(
                _row(
                    source="agent:reader",
                    relation="read",
                    target=f"bead:{issue.id}",
                    origin="read",
                    description=f"agent:reader read bead:{issue.id}",
                    created_by="agent:reader",
                    created_at="2026-09-10T00:00:00Z",
                ),
                project_key=store.project_key,
                operation_id=operation_id,
            )
            for operation_id in (
                "11111111111111111111111111111111",
                "22222222222222222222222222222222",
            )
        )
        local_root = artifact_link_local_event_root(store.project_key)

        reports = tuple(
            publish_artifact_link_events(
                store,
                (event,),
                push_after_commit=False,
                mutation_origin="machine",
            )
            for event in events
        )

        assert [report.published for report in reports] == [1, 1]
        assert {path for report in reports for path in report.durable_event_paths} == {
            local_root / canonical_artifact_link_event_object(event).relative_path
            for event in events
        }
        assert all(
            report.event_paths == report.durable_event_paths for report in reports
        )
        [expected] = rows_from_events(events)
        assert set(active_operation_ids_for_row(store, expected)) == {
            "11111111111111111111111111111111",
            "22222222222222222222222222222222",
        }
        [link] = project.show(issue.id).links
        assert link.uses == 2
        [aggregate_row] = store.load_aggregate()["rows"]
        assert aggregate_row["uses"] == 2


def test_publish_bead_only_event_quarantines_local_operation_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    with BeadProject.init(tmp_path / "beads") as project:
        issue = project.create("Read target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=project.beads_dir,
        )
        operation_id = "33333333333333333333333333333333"

        def event(description: str) -> dict[str, object]:
            return observation_or_put_event_from_row(
                _row(
                    source="agent:reader",
                    relation="read",
                    target=f"bead:{issue.id}",
                    origin="read",
                    description=description,
                    created_by="agent:reader",
                    created_at="2026-09-10T00:00:00Z",
                ),
                project_key=store.project_key,
                operation_id=operation_id,
            )

        publish_artifact_link_events(
            store,
            (event(f"agent:reader read bead:{issue.id}"),),
            push_after_commit=False,
            mutation_origin="machine",
        )
        local_root = artifact_link_local_event_root(store.project_key)
        canonical = event(f"agent:reader read bead:{issue.id}")
        canonical_object = canonical_artifact_link_event_object(canonical)
        event_path = local_root / canonical_object.relative_path

        rejected = event("changed payload")
        rejected_object = canonical_artifact_link_event_object(rejected)
        report = publish_artifact_link_events(
            store,
            (rejected,),
            push_after_commit=False,
            mutation_origin="machine",
        )

        assert report.published == 0
        assert report.quarantined_event_keys == (
            (operation_id, rejected_object.digest),
        )
        assert event_path.read_bytes() == canonical_object.payload
        [record_path] = report.quarantine_paths
        assert (
            json.loads(record_path.read_text(encoding="utf-8"))["rejected_event"]
            == rejected
        )
        [link] = project.show(issue.id).links
        assert link.uses == 1
        [aggregate_row] = store.load_aggregate()["rows"]
        assert aggregate_row["uses"] == 1


def test_publish_event_with_unresolved_document_owner_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={},
        unresolved_document_kinds={"plan": "plans hidden clone is unavailable"},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="plan:202609/a.md",
            relation="related",
            target="agent:planner",
            origin="manual",
        ),
        project_key=store.project_key,
        operation_id="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    )

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 0
    assert report.published_operation_ids == ()
    assert report.event_paths == ()
    assert report.durable_event_paths == ()
    assert any("plan:202609/a.md" in item for item in report.skip_diagnostics)
    assert store.load_aggregate().get("rows", ()) == []
