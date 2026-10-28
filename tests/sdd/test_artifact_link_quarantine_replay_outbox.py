"""Quarantine replay evidence: outbox and publication path tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_canonical import canonical_artifact_link_event_object
from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd.artifact_link_event_publisher import (
    observation_or_put_event_from_row,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import _init_plans_repo
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    row as make_row,
)
from tests.sdd._artifact_link_quarantine_replay_helpers import (
    colliding_pair,
    event_digest,
)
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


def _event_target(event: dict[str, object]) -> str:
    kind = event.get("kind")
    if not isinstance(kind, dict):
        raise AssertionError("event is missing kind")
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        raise AssertionError("event kind is missing an edge")
    if edge.get("kind") == "undirected":
        return str(edge.get("right_ref") or "")
    return str(edge.get("target_ref") or "")


def _outbox_event(store: ArtifactLinkStore, target: str, description: str, op: str):
    return observation_or_put_event_from_row(
        make_row(
            source="plan:doc.md",
            relation="related",
            target=target,
            origin="derived",
            description=description,
            created_by="sase",
        ),
        project_key=store.project_key,
        operation_id=op,
    )


def test_empty_store_outbox_collision_restarts_after_rewrite_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    operation_id = "f" * 32
    first = _outbox_event(store, "plan:original.md", "first payload", operation_id)
    second = _outbox_event(store, "plan:replay.md", "replay payload", operation_id)
    unrelated = _outbox_event(store, "plan:fresh.md", "unrelated event", "1" * 32)
    for queued in (first, second, unrelated):
        append_artifact_link_outbox_event(
            project_key=store.project_key,
            agent_name="sase",
            run_id="machine",
            event=queued,
        )

    def fail_rewrite(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated interruption before outbox rewrite")

    with monkeypatch.context() as patch:
        patch.setattr(
            "sase.sdd._artifact_link_outbox_drain._rewrite_without_ids",
            fail_rewrite,
        )
        with pytest.raises(RuntimeError, match="before outbox rewrite"):
            drain_artifact_link_outbox(
                store=store,
                drop_stale_terminal=False,
                push_after_commit=False,
            )

    quarantine_paths = list(
        (repo / "link-events" / "quarantine" / "v1").rglob("*.json")
    )
    assert len(quarantine_paths) == 1
    before = quarantine_paths[0].read_bytes()
    assert len(read_artifact_link_outbox_entries(store.project_key)) == 3
    snapshot = store.artifact_link_event_snapshot(strict=True)
    accepted_targets = {_event_target(event) for event in snapshot.accepted_events}
    collision_targets = accepted_targets & {"plan:original.md", "plan:replay.md"}
    assert len(collision_targets) == 1
    accepted_target = next(iter(collision_targets))
    assert "plan:fresh.md" in accepted_targets
    row_targets = {
        row["target_ref"]
        for row in store.load_aggregate()["rows"]
        if isinstance(row, dict)
    }
    assert "plan:fresh.md" in row_targets
    assert accepted_target in row_targets
    assert len(row_targets) == 2
    winner = first if _event_target(first) == accepted_target else second
    winner_path = repo / canonical_artifact_link_event_object(winner).relative_path
    winner_bytes = winner_path.read_bytes()

    restarted = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first_drain = drain_artifact_link_outbox(
        store=restarted,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert first_drain.quarantined == 1
    assert len(read_artifact_link_outbox_entries(store.project_key)) == 0
    records = list((repo / "link-events" / "quarantine" / "v1").rglob("*.json"))
    assert len(records) == 1
    assert records[0].read_bytes() == before
    assert winner_path.read_bytes() == winner_bytes
    later = restarted.artifact_link_event_snapshot(strict=True)
    assert later.healthy is True
    assert len(later.quarantine_findings) == 1

    second_drain = drain_artifact_link_outbox(
        store=restarted,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert second_drain.queued == 0
    assert second_drain.quarantined == 0
    assert records[0].read_bytes() == before
    assert winner_path.read_bytes() == winner_bytes
    assert restarted.load_aggregate()["rows"] == store.load_aggregate()["rows"]


def test_rejected_payload_direct_then_outbox_and_reverse_preserve_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first, second = colliding_pair(origin="derived")
    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
        origin="derived",
    )
    report = publish_artifact_link_events(
        store,
        (first, second, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert len(report.quarantine_paths) == 1
    before = report.quarantine_paths[0].read_bytes()
    loser_digest = report.quarantined_event_keys[0][1]
    loser = second if event_digest(second) == loser_digest else first
    append_artifact_link_outbox_event(
        project_key=store.project_key,
        agent_name="sase",
        run_id="machine",
        event=loser,
    )
    drained = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert drained.quarantined == 1
    assert report.quarantine_paths[0].read_bytes() == before

    reverse_root = tmp_path / "reverse"
    reverse_root.mkdir()
    redirect_sase_home(monkeypatch, reverse_root / ".sase")
    reverse_plans = reverse_root / "plans"
    _init_plans_repo(reverse_plans)
    reverse_store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": reverse_plans},
    )
    for queued in (first, second, unrelated):
        append_artifact_link_outbox_event(
            project_key=reverse_store.project_key,
            agent_name="sase",
            run_id="machine",
            event=queued,
        )
    outbox_drain = drain_artifact_link_outbox(
        store=reverse_store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert outbox_drain.quarantined == 1
    reverse_records = list(
        (reverse_plans / "link-events" / "quarantine" / "v1").rglob("*.json")
    )
    assert len(reverse_records) == 1
    reverse_before = reverse_records[0].read_bytes()
    reverse_loser_digest = (
        reverse_store.artifact_link_event_snapshot(strict=True)
        .quarantine_findings[0]
        .rejected_digest
    )
    reverse_loser = second if event_digest(second) == reverse_loser_digest else first
    retry = publish_artifact_link_events(
        reverse_store,
        (reverse_loser,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert retry.quarantined_event_keys
    assert reverse_records[0].read_bytes() == reverse_before


def test_document_sidecar_and_ownerless_collision_lanes_settle_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    sidecar = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": repo},
    )
    first, second = colliding_pair()
    unrelated = edge_event(
        "b" * 32,
        target="plan:202608/fresh.md",
        description="unrelated append",
    )
    sidecar_report = publish_artifact_link_events(
        sidecar,
        (first, second, unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert sidecar_report.published_operation_ids == ("a" * 32, "b" * 32)
    assert len(sidecar_report.quarantine_paths) == 1
    sidecar_bytes = sidecar_report.quarantine_paths[0].read_bytes()
    snapshot = sidecar.artifact_link_event_snapshot(strict=True)
    assert snapshot.healthy is True
    assert len(snapshot.quarantine_findings) == 1

    ownerless = ArtifactLinkStore(project_key=PROJECT_KEY, sidecar_roots={})
    local_first = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:planner",
            origin="manual",
            description="ownerless original",
        ),
        project_key=PROJECT_KEY,
        operation_id="c" * 32,
    )
    local_second = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:other",
            origin="manual",
            description="ownerless replay",
        ),
        project_key=PROJECT_KEY,
        operation_id="c" * 32,
    )
    local_unrelated = observation_or_put_event_from_row(
        make_row(
            source="agent:reader",
            relation="related",
            target="agent:fresh",
            origin="manual",
            description="ownerless unrelated",
        ),
        project_key=PROJECT_KEY,
        operation_id="d" * 32,
    )
    local_report = publish_artifact_link_events(
        ownerless,
        (local_first, local_second, local_unrelated),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert local_report.published == 2
    assert len(local_report.quarantine_paths) == 1
    local_before = local_report.quarantine_paths[0].read_bytes()
    local_loser_digest = local_report.quarantined_event_keys[0][1]
    local_loser = (
        local_second
        if event_digest(local_second) == local_loser_digest
        else local_first
    )
    local_retry = publish_artifact_link_events(
        ownerless,
        (local_loser,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert local_retry.quarantined_event_keys == local_report.quarantined_event_keys
    assert local_report.quarantine_paths[0].read_bytes() == local_before
    assert sidecar_report.quarantine_paths[0].read_bytes() == sidecar_bytes
