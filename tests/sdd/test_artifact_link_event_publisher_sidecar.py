"""Document-sidecar publication, collision, and quarantine tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object,
)
from sase.sdd.artifact_link_event_publisher import (
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
