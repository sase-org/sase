"""Acceptance coverage for artifact-link event import and bead projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.sdd._artifact_link_cutover_state import read_artifact_link_cutover_marker
from sase.sdd.artifact_link_event_publisher import publish_artifact_link_events
from sase.sdd.artifact_link_import_indexes import import_artifact_link_indexes
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_acceptance_helpers import (
    PROJECT_KEY,
    _baseline_event,
    _cluster,
    _edge_put,
    _init_local_repo,
    _write_legacy_index,
)
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes
from tests.sdd_store._helpers import commit_all


def test_import_replay_and_managed_markdown_projection_remain_event_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy import plus managed markdown projection reduce to one truth."""

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "machine" / "plans"
    _init_local_repo(plans, {"202609/imported.md": "# Imported\n"})
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans},
    )
    legacy = _write_legacy_index(
        plans,
        "plan:202609/imported.md",
        rows=[
            _row(
                source="plan:202609/imported.md",
                relation="related",
                target="plan:202609/target.md",
                description="legacy relationship",
            )
        ],
    )
    commit_all(plans, "legacy link index")

    first = import_artifact_link_indexes(store).plan
    second = import_artifact_link_indexes(store).plan

    assert first.import_id == second.import_id
    assert first.operation_id == second.operation_id
    assert json.dumps(first.baseline_event, sort_keys=True) == json.dumps(
        second.baseline_event,
        sort_keys=True,
    )

    applied = import_artifact_link_indexes(store, apply=True, push_after_commit=False)

    assert applied.applied is True
    assert read_artifact_link_cutover_marker(plans) is not None
    assert any(path.exists() for path in applied.event_paths)
    [row] = store.load_durable_rows()
    assert row["description"] == "legacy relationship"
    assert row["target_ref"] == "plan:202609/target.md"
    assert legacy.exists()

    new_event = _edge_put(
        "eeeeeeeeeeeeeeeeeeeeeeeeeeee1111",
        source="plan:202609/imported.md",
        relation="related",
        target="plan:202609/after-import.md",
        description="event after import",
    )
    publish_artifact_link_events(
        store,
        (new_event,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    reduced_rows = store.load_artifact_rows("plan:202609/imported.md")

    assert {
        (
            row["relation"],
            frozenset((row["source_ref"], row["target_ref"])),
            row["description"],
        )
        for row in reduced_rows
    } == {
        (
            "related",
            frozenset(("plan:202609/imported.md", "plan:202609/target.md")),
            "legacy relationship",
        ),
        (
            "related",
            frozenset(("plan:202609/imported.md", "plan:202609/after-import.md")),
            "event after import",
        ),
    }


def test_baseline_event_projects_multiple_edges_to_one_bead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = _cluster(tmp_path, monkeypatch)
    machine = cluster.machine_a
    tracked_bead = cluster.bead_project.create("Baseline target", IssueType.PLAN)
    first = _row(
        source="plan:202609/baseline-a.md",
        relation="implements",
        target=f"bead:{tracked_bead.id}",
        origin="migrated",
        description="first imported edge",
        created_by="agent:importer.athena.worker",
        created_at="2026-09-10T00:00:00Z",
    )
    second = _row(
        source="plan:202609/baseline-b.md",
        relation="implements",
        target=f"bead:{tracked_bead.id}",
        origin="migrated",
        description="second imported edge",
        created_by="agent:importer.athena.worker",
        created_at="2026-09-10T00:00:00Z",
    )

    report = publish_artifact_link_events(
        machine.store,
        (_baseline_event("eeeeeeeeeeeeeeeeeeeeeeeeeeee2222", (first, second)),),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.publication_error is None
    assert report.published == 1
    issue = cluster.bead_project.show(tracked_bead.id)
    projected = {
        (link.target_ref, link.relation, link.direction) for link in issue.links
    }
    assert projected == {
        ("plan:202609/baseline-a.md", "implements", "in"),
        ("plan:202609/baseline-b.md", "implements", "in"),
    }
