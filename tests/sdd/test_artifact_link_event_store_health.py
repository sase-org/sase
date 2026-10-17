"""Artifact-link event-store health and tombstone tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_canonical import rows_from_events
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_event
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    remove_event,
    row as make_row,
    make_store,
    write_event,
)


def test_event_health_reports_orphaned_tombstones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    write_event(tmp_path / "plans", remove_event("2" * 32, observed=("9" * 32,)))

    snapshot = store.artifact_link_event_snapshot(strict=False)

    assert snapshot.orphaned_tombstones
    assert snapshot.healthy is True
    assert snapshot.problem_messages == snapshot.orphaned_tombstones
    store.artifact_link_event_snapshot(strict=True)


def test_orphaned_tombstone_does_not_block_unrelated_durable_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    events = (
        edge_event(
            "a" * 32,
            source="plan:202609/hot.md",
            relation="related",
            target="plan:202609/target.md",
            description="unrelated visible edge",
        ),
        remove_event(
            "b" * 32,
            source="plan:202609/late.md",
            relation="related",
            target="plan:202609/other.md",
            observed=("c" * 32,),
        ),
    )
    for event in events:
        write_event(tmp_path / "plans", event)

    assert store.load_durable_rows() == rows_from_events(events)
    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.orphaned_tombstones


def test_orphaned_pending_tombstone_does_not_block_unrelated_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    visible = edge_event(
        "a" * 32,
        source="plan:202609/hot.md",
        relation="related",
        target="plan:202609/target.md",
        description="unrelated visible edge",
    )
    tombstone = remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    write_event(tmp_path / "plans", visible)
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="agent:pending.athena.worker",
        run_id="run-1",
        event=tombstone,
    )

    assert store.load_durable_rows() == rows_from_events((visible, tombstone))
    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.pending_event_count == 1
    assert snapshot.orphaned_tombstones


def test_orphaned_tombstone_prevents_legacy_fallback_resurrection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    stale_row = make_row(
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        description="stale legacy row",
    )
    store.upsert_row(stale_row)
    tombstone = remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    write_event(tmp_path / "plans", tombstone)

    assert store.load_artifact_rows("plan:202609/late.md") == ()
    assert store.load_durable_rows() == ()


def test_orphaned_tombstone_converges_when_predecessor_arrives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    visible = edge_event(
        "a" * 32,
        source="plan:202609/hot.md",
        relation="related",
        target="plan:202609/target.md",
        description="unrelated visible edge",
    )
    predecessor = edge_event(
        "c" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        description="removed predecessor",
    )
    tombstone = remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    write_event(tmp_path / "plans", visible)
    write_event(tmp_path / "plans", tombstone)

    assert store.artifact_link_event_snapshot(strict=True).orphaned_tombstones

    write_event(tmp_path / "plans", predecessor)

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.orphaned_tombstones == ()
    assert store.load_durable_rows() == rows_from_events(
        (visible, tombstone, predecessor)
    )
