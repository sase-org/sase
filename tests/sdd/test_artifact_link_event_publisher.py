"""Tests for immutable artifact-link event publication."""

from __future__ import annotations

import subprocess
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
    edge_remove_event,
    observation_or_put_event_from_row,
    publish_artifact_link_events,
    rows_from_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init_repo(repo: Path, document: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.invalid")
    path = repo / document
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Document\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--count", "HEAD").strip())


def _status(repo: Path) -> str:
    return _git(repo, "status", "--porcelain", "--untracked-files=all")


def test_publish_event_writes_dual_document_roots_and_replays_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_repo(plans, "202609/a.md")
    _init_repo(research, "202609/b.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="plan:202609/a.md",
            relation="related",
            target="research:202609/b.md",
            origin="manual",
        ),
        project_key=store.project_key,
        operation_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    event_object = canonical_artifact_link_event_object(event)

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published_operation_ids == ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
    assert report.published == 1
    assert {path.parents[3] for path in report.event_paths} == {
        plans,
        research,
    }
    assert (plans / event_object.relative_path).read_bytes() == event_object.payload
    assert (research / event_object.relative_path).read_bytes() == event_object.payload
    assert not list(plans.glob("links/**/*"))
    assert not list(research.glob("links/**/*"))
    assert _commit_count(plans) == 2
    assert _commit_count(research) == 2
    assert _status(plans) == ""
    assert _status(research) == ""
    [row] = store.load_aggregate()["rows"]
    assert row["source_ref"] == "plan:202609/a.md"
    assert row["target_ref"] == "research:202609/b.md"

    replay = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert replay.published == 1
    assert replay.committed is False
    assert _commit_count(plans) == 2
    assert _commit_count(research) == 2
    assert _status(plans) == ""
    assert _status(research) == ""


def test_publish_event_rejects_same_path_with_different_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, "202609/a.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    event = observation_or_put_event_from_row(
        _row(source="plan:202609/a.md", target="agent:reader", origin="manual"),
        project_key=store.project_key,
        operation_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    event_object = canonical_artifact_link_event_object(event)
    path = plans / event_object.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")

    # Snapshot validation rejects malformed bytes before publication reaches
    # the installer's same-path byte comparison.
    with pytest.raises(RuntimeError, match="artifact-link event store is invalid"):
        publish_artifact_link_events(
            store,
            (event,),
            push_after_commit=False,
            mutation_origin="machine",
        )

    assert _commit_count(plans) == 1


def test_publish_event_quarantines_committed_collision_and_keeps_store_writable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, "202609/a.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    operation_id = "c" * 32
    first = observation_or_put_event_from_row(
        _row(
            source="agent:reader",
            relation="read",
            target="plan:202609/a.md",
            origin="read",
            description="first read",
        ),
        project_key=store.project_key,
        operation_id=operation_id,
    )
    second = observation_or_put_event_from_row(
        _row(
            source="agent:reader",
            relation="read",
            target="plan:202609/a.md",
            origin="read",
            description="changed read",
        ),
        project_key=store.project_key,
        operation_id=operation_id,
    )
    publish_artifact_link_events(
        store,
        (first,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    report = publish_artifact_link_events(
        store,
        (second,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    second_object = canonical_artifact_link_event_object(second)
    assert report.published == 0
    assert report.quarantined_event_keys == ((operation_id, second_object.digest),)
    assert len(report.quarantine_paths) == 1
    [record_path] = report.quarantine_paths
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["rejected_event"] == second
    assert record["rejected_digest"] == second_object.digest
    snapshot = store.artifact_link_event_snapshot(include_pending=False, strict=True)
    assert snapshot.accepted_events == (first,)
    assert len(snapshot.quarantine_findings) == 1
    assert snapshot.quarantine_findings[0].rejected_event == second
    assert _commit_count(plans) == 3
    assert _status(plans) == ""

    unrelated = observation_or_put_event_from_row(
        _row(
            source="agent:reader",
            relation="read",
            target="plan:202609/a.md",
            origin="read",
            description="fresh unrelated operation",
        ),
        project_key=store.project_key,
        operation_id="d" * 32,
    )
    unrelated_report = publish_artifact_link_events(
        store,
        (unrelated,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert unrelated_report.published_operation_ids == ("d" * 32,)
    assert _commit_count(plans) == 4


def test_conflicting_edge_remove_is_quarantined_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, "202609/a.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    operation_id = "e" * 32
    original = observation_or_put_event_from_row(
        _row(
            source="plan:202609/a.md",
            relation="related",
            target="plan:202609/original.md",
            description="original edge",
        ),
        project_key=store.project_key,
        operation_id=operation_id,
    )
    publish_artifact_link_events(
        store,
        (original,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    remove = edge_remove_event(
        project_key=store.project_key,
        operation_id=operation_id,
        source_ref="plan:202609/a.md",
        relation="related",
        target_ref="plan:202609/original.md",
        created_by="agent:event.athena.worker",
        origin="manual",
        created_at="2026-09-09T00:00:00Z",
        observed_operation_ids=("f" * 32,),
    )

    report = publish_artifact_link_events(
        store,
        (remove,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    remove_object = canonical_artifact_link_event_object(remove)
    assert report.published == 0
    assert report.quarantined_event_keys == ((operation_id, remove_object.digest),)
    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.accepted_events == (original,)
    assert snapshot.rows == rows_from_events((original,))
    assert len(snapshot.quarantine_findings) == 1
    assert snapshot.quarantine_findings[0].rejected_event == remove
    assert _commit_count(plans) == 3


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


def test_publish_bead_owner_without_bead_store_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_repo(plans, "202609/a.md")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="plan:202609/a.md",
            relation="implements",
            target="bead:sase-yy.4",
            origin="derived",
        ),
        project_key=store.project_key,
        operation_id="ffffffffffffffffffffffffffffffff",
    )

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 0
    assert report.published_operation_ids == ()
    assert report.event_paths
    assert any("bead store is unavailable" in item for item in report.skip_diagnostics)
    assert store.load_aggregate().get("rows", ()) == []
