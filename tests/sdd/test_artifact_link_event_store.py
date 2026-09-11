"""Artifact-link event-reader integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_cutover_state import (
    ArtifactLinkBaselineEventIdentity,
    ArtifactLinkCutoverImportIdentity,
    ArtifactLinkCutoverRole,
    artifact_link_cutover_marker_path,
    build_artifact_link_cutover_marker_payload,
    parse_artifact_link_cutover_marker_payload,
)
from sase.sdd._artifact_link_event_canonical import rows_from_events
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_event
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    artifact_link_aggregate_path,
)
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import (
    _row,
    _store,
    allow_machine_sidecar_writes,
)


PROJECT_KEY = "gh_sase-org__sase"


def test_duplicate_endpoint_event_objects_reduce_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    event = _edge_event("a" * 32, description="canonical event row")
    _write_event(tmp_path / "plans", event)
    _write_event(tmp_path / "research", event)

    rows = store.load_durable_rows()
    snapshot = store.artifact_link_event_snapshot(strict=True)

    assert snapshot.durable_event_count == 2
    assert len(rows) == 1
    assert rows[0]["description"] == "canonical event row"


def test_reconciliation_reduces_event_union_before_deduping_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left, right = _paired_stores(tmp_path, monkeypatch)
    _write_event(
        left.sidecar_roots["plan"],
        _edge_event(
            "a" * 32,
            source="agent:reader.athena.worker",
            relation="read",
            target="plan:202609/hot.md",
            origin="read",
            occurrences=1,
        ),
    )
    _write_event(
        right.sidecar_roots["plan"],
        _edge_event(
            "b" * 32,
            source="agent:reader.athena.worker",
            relation="read",
            target="plan:202609/hot.md",
            origin="read",
            occurrences=1,
        ),
    )
    _patch_reconciliation_stores(monkeypatch, left, right)

    [row] = left.preview_reconciled_aggregate()["rows"]

    assert row["source_ref"] == "agent:reader.athena.worker"
    assert row["target_ref"] == "plan:202609/hot.md"
    assert row["uses"] == 2


def test_reconciliation_unions_tombstones_with_sibling_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    left, right = _paired_stores(tmp_path, monkeypatch)
    _write_event(left.sidecar_roots["plan"], _edge_event("1" * 32))
    _write_event(
        right.sidecar_roots["plan"],
        _remove_event("2" * 32, observed=("1" * 32,)),
    )
    _patch_reconciliation_stores(monkeypatch, left, right)

    aggregate = left.preview_reconciled_aggregate()

    assert aggregate["rows"] == []


def test_event_ordering_chooses_newest_edge_put(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_event(
        tmp_path / "plans",
        _edge_event(
            "b" * 32,
            created_at="2026-09-01T00:00:00Z",
            description="old description",
        ),
    )
    _write_event(
        tmp_path / "plans",
        _edge_event(
            "c" * 32,
            created_at="2026-09-02T00:00:00Z",
            description="new description",
        ),
    )

    [row] = store.load_durable_rows()

    assert row["description"] == "new description"


def test_pending_event_outbox_entries_are_visible_with_age_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="agent:pending.athena.worker",
        run_id="run-1",
        event=_edge_event("d" * 32, target="plan:202608/pending.md"),
        now=100.0,
    )

    rows = store.load_durable_rows()
    snapshot = store.artifact_link_event_snapshot(strict=True, now=200.0)

    assert [row["target_ref"] for row in rows] == ["plan:202608/pending.md"]
    assert snapshot.pending_event_count == 1
    assert snapshot.pending_stats.count == 1
    assert snapshot.pending_stats.oldest_age_seconds == 100.0
    assert snapshot.pending_stats.p95_age_seconds == 100.0


def test_legacy_event_overlap_rejected_before_cutover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row(relation="cites"))
    _write_event(
        tmp_path / "plans",
        _edge_event("e" * 32, relation="cites"),
    )

    with pytest.raises(RuntimeError, match="legacy/event overlap rejected"):
        store.load_durable_rows()


def test_imported_cutover_ignores_legacy_rows_when_events_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row(relation="cites", description="legacy row"))
    _write_event(
        tmp_path / "plans",
        _edge_event("e" * 32, relation="cites", description="event row"),
    )
    _write_imported_marker(store)

    [row] = store.load_durable_rows()

    assert row["description"] == "event row"


def test_pending_read_events_increment_legacy_rows_without_overlap_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="agent:reader",
            relation="read",
            target="plan:202608/a.md",
            origin="read",
            uses=2,
        )
    )
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="reader",
        run_id="run-1",
        event=_edge_event(
            "3" * 32,
            source="agent:reader",
            relation="read",
            target="plan:202608/a.md",
            origin="read",
            occurrences=1,
        ),
    )

    [row] = store.load_durable_rows()

    assert row["uses"] == 3


def test_alias_event_reduces_late_old_ref_observation_to_new_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_event(
        tmp_path / "plans",
        _alias_event(
            "f" * 32,
            old_ref="plan:202608/old.md",
            new_ref="plan:202608/new.md",
        ),
    )
    _write_event(
        tmp_path / "plans",
        _edge_event(
            "1" * 32,
            source="agent:reader.athena.worker",
            target="plan:202608/old.md",
            relation="read",
            origin="read",
            occurrences=3,
        ),
    )

    rows = store.load_artifact_rows("plan:202608/new.md")

    assert len(rows) == 1
    assert rows[0]["target_ref"] == "plan:202608/new.md"
    assert rows[0]["uses"] == 3


def test_projected_rows_do_not_become_durable_store_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    path = artifact_link_aggregate_path(PROJECT_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generation": 1,
                "rows": [_row(origin="projected", created_by="projection")],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert store.load_durable_rows() == ()


def test_event_health_reports_orphaned_tombstones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    _write_event(tmp_path / "plans", _remove_event("2" * 32, observed=("9" * 32,)))

    snapshot = store.artifact_link_event_snapshot(strict=False)

    assert snapshot.orphaned_tombstones
    assert snapshot.healthy is True
    assert snapshot.problem_messages == snapshot.orphaned_tombstones
    store.artifact_link_event_snapshot(strict=True)


def test_orphaned_tombstone_does_not_block_unrelated_durable_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    events = (
        _edge_event(
            "a" * 32,
            source="plan:202609/hot.md",
            relation="related",
            target="plan:202609/target.md",
            description="unrelated visible edge",
        ),
        _remove_event(
            "b" * 32,
            source="plan:202609/late.md",
            relation="related",
            target="plan:202609/other.md",
            observed=("c" * 32,),
        ),
    )
    for event in events:
        _write_event(tmp_path / "plans", event)

    assert store.load_durable_rows() == rows_from_events(events)
    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.orphaned_tombstones


def test_orphaned_pending_tombstone_does_not_block_unrelated_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    visible = _edge_event(
        "a" * 32,
        source="plan:202609/hot.md",
        relation="related",
        target="plan:202609/target.md",
        description="unrelated visible edge",
    )
    tombstone = _remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    _write_event(tmp_path / "plans", visible)
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
    store = _store(tmp_path, monkeypatch)
    stale_row = _row(
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        description="stale legacy row",
    )
    store.upsert_row(stale_row)
    tombstone = _remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    _write_event(tmp_path / "plans", tombstone)

    assert store.load_artifact_rows("plan:202609/late.md") == ()
    assert store.load_durable_rows() == ()


def test_orphaned_tombstone_converges_when_predecessor_arrives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, monkeypatch)
    visible = _edge_event(
        "a" * 32,
        source="plan:202609/hot.md",
        relation="related",
        target="plan:202609/target.md",
        description="unrelated visible edge",
    )
    predecessor = _edge_event(
        "c" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        description="removed predecessor",
    )
    tombstone = _remove_event(
        "b" * 32,
        source="plan:202609/late.md",
        relation="related",
        target="plan:202609/other.md",
        observed=("c" * 32,),
    )
    _write_event(tmp_path / "plans", visible)
    _write_event(tmp_path / "plans", tombstone)

    assert store.artifact_link_event_snapshot(strict=True).orphaned_tombstones

    _write_event(tmp_path / "plans", predecessor)

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert snapshot.orphaned_tombstones == ()
    assert store.load_durable_rows() == rows_from_events(
        (visible, tombstone, predecessor)
    )


def _edge_event(
    operation_id: str,
    *,
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    description: str = "event-backed link",
    origin: str = "manual",
    created_at: str = "2026-09-09T00:00:00Z",
    occurrences: int = 1,
) -> dict[str, object]:
    edge = {
        "kind": "directed",
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
    }
    kind = (
        {
            "type": "observation",
            "edge": edge,
            "description": description,
            "occurrences": occurrences,
        }
        if origin == "read"
        else {
            "type": "edge-put",
            "edge": edge,
            "description": description,
            "observed_operation_ids": [],
        }
    )
    return _canonicalize_event(
        {
            "schema_version": int(
                require_rust_binding("artifact_link_event_schema_version")()
            ),
            "project_key": PROJECT_KEY,
            "operation_id": operation_id,
            "created_by": "agent:event.athena.worker",
            "origin": origin,
            "created_at": created_at,
            "kind": kind,
        }
    )


def _remove_event(
    operation_id: str,
    *,
    source: str = "plan:202608/a.md",
    relation: str = "implements",
    target: str = "plan:202608/b.md",
    observed: tuple[str, ...],
) -> dict[str, object]:
    return _canonicalize_event(
        {
            "schema_version": int(
                require_rust_binding("artifact_link_event_schema_version")()
            ),
            "project_key": PROJECT_KEY,
            "operation_id": operation_id,
            "created_by": "agent:event.athena.worker",
            "origin": "manual",
            "created_at": "2026-09-09T00:00:00Z",
            "kind": {
                "type": "edge-remove",
                "edge": {
                    "kind": "directed",
                    "source_ref": source,
                    "relation": relation,
                    "target_ref": target,
                },
                "observed_operation_ids": list(observed),
            },
        }
    )


def _alias_event(
    operation_id: str,
    *,
    old_ref: str,
    new_ref: str,
) -> dict[str, object]:
    return _canonicalize_event(
        {
            "schema_version": int(
                require_rust_binding("artifact_link_event_schema_version")()
            ),
            "project_key": PROJECT_KEY,
            "operation_id": operation_id,
            "created_by": "agent:event.athena.worker",
            "origin": "migrated",
            "created_at": "2026-09-09T00:00:00Z",
            "kind": {
                "type": "alias",
                "old_ref": old_ref,
                "new_ref": new_ref,
            },
        }
    )


def _canonicalize_event(event: dict[str, object]) -> dict[str, object]:
    return dict(require_rust_binding("artifact_link_event_canonicalize")(event))


def _write_event(root: Path, event: dict[str, object]) -> Path:
    digest = str(require_rust_binding("artifact_link_event_digest")(event))
    relpath = str(require_rust_binding("artifact_link_event_path_for_digest")(digest))
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        str(require_rust_binding("artifact_link_event_canonical_json")(event)),
        encoding="utf-8",
    )
    return path


def _write_imported_marker(store: ArtifactLinkStore) -> None:
    digest = "a" * 64
    payload = build_artifact_link_cutover_marker_payload(
        state="imported",
        project_key=PROJECT_KEY,
        event_store_schema_version=1,
        event_store_minimum_event_schema_version=int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        import_identity=ArtifactLinkCutoverImportIdentity(
            import_id="legacy-v2-links-test",
            operation_id="b" * 32,
            source_head="sha256:" + "c" * 64,
            created_at="2026-09-10T00:00:00Z",
        ),
        roles=(
            ArtifactLinkCutoverRole(
                role="plans",
                kind="plan",
                head="d" * 40,
                links_tree="sha256:" + "e" * 64,
                remote_url="<none>",
            ),
            ArtifactLinkCutoverRole(
                role="research",
                kind="research",
                head="f" * 40,
                links_tree="sha256:" + "0" * 64,
                remote_url="<none>",
            ),
        ),
        baseline_event=ArtifactLinkBaselineEventIdentity(
            digest=digest,
            path=f"link-events/v1/{digest[:2]}/{digest}.json",
        ),
    )
    marker_bytes = parse_artifact_link_cutover_marker_payload(payload).canonical_bytes
    for root in store.sidecar_roots.values():
        path = artifact_link_cutover_marker_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker_bytes)


def _paired_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ArtifactLinkStore, ArtifactLinkStore]:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    stores: list[ArtifactLinkStore] = []
    for name in ("left", "right"):
        plans = tmp_path / name / "plans"
        research = tmp_path / name / "research"
        plans.mkdir(parents=True)
        research.mkdir(parents=True)
        stores.append(
            ArtifactLinkStore(
                project_key=PROJECT_KEY,
                sidecar_roots={"plan": plans, "research": research},
            )
        )
    return stores[0], stores[1]


def _patch_reconciliation_stores(
    monkeypatch: pytest.MonkeyPatch,
    left: ArtifactLinkStore,
    right: ArtifactLinkStore,
) -> None:
    def _stores(self: ArtifactLinkStore) -> tuple[ArtifactLinkStore, ...]:
        if self is left:
            return (left, right)
        return (self,)

    monkeypatch.setattr(ArtifactLinkStore, "_iter_reconciliation_stores", _stores)
