"""Scoped input reuse for artifact-link event snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_store import ArtifactLinkEventStoreAdapter
from sase.sdd._artifact_link_snapshot_memo import artifact_link_snapshot_memo
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_event_store_test_helpers import (
    PROJECT_KEY,
    edge_event,
    row as make_row,
    write_event,
)


def _adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ArtifactLinkEventStoreAdapter:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    return ArtifactLinkEventStoreAdapter(
        PROJECT_KEY,
        {"plan": plans, "research": research},
    )


def _count_snapshot_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from sase.sdd import _artifact_link_event_store as event_store_module
    from sase.sdd import _artifact_link_outbox_io as outbox_io

    counts = [0, 0]
    require_binding = event_store_module.require_rust_binding
    read_records = outbox_io._read_outbox_records_unlocked

    def _count_binding(name: str):  # type: ignore[no-untyped-def]
        binding = require_binding(name)
        if name != "artifact_link_event_validate_bytes":
            return binding

        def _validate(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            counts[0] += 1
            return binding(*args, **kwargs)

        return _validate

    def _count_records(path: Path, project_key: str):  # type: ignore[no-untyped-def]
        counts[1] += 1
        return read_records(path, project_key)

    monkeypatch.setattr(event_store_module, "require_rust_binding", _count_binding)
    monkeypatch.setattr(outbox_io, "_read_outbox_records_unlocked", _count_records)
    return counts


def _append_pending_event(target: str, *, created_at: float):
    from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_entry

    return append_artifact_link_outbox_entry(
        project_key=PROJECT_KEY,
        agent_name="reader",
        run_id="run-1",
        row=make_row(
            source="agent:reader.athena.worker",
            relation="read",
            target=target,
            origin="read",
        ),
        now=created_at,
    )


def test_scoped_snapshots_reuse_inputs_and_invalidate_changed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(tmp_path, monkeypatch)
    durable_root = tmp_path / "plans"
    write_event(durable_root, edge_event("a" * 32, target="plan:202611/first.md"))
    first_pending = _append_pending_event("plan:202611/pending-a.md", created_at=100)
    counts = _count_snapshot_reads(monkeypatch)

    with artifact_link_snapshot_memo():
        first = adapter.snapshot(now=200, strict=True)
        second = adapter.snapshot(now=200, strict=True)
        assert first == second
        assert counts == [1, 1]

        write_event(
            durable_root,
            edge_event("b" * 32, target="plan:202611/second.md"),
        )
        second_pending = _append_pending_event(
            "plan:202611/pending-b.md",
            created_at=150,
        )
        excluded = adapter.snapshot(
            now=200,
            strict=True,
            exclude_pending_event_ids=(second_pending.id,),
        )
        assert excluded.pending_event_count == 1
        assert counts == [2, 2]

        latest = adapter.snapshot(now=200, strict=True)
        assert latest.pending_event_count == 2
        assert {event["operation_id"] for event in latest.pending_events} == {
            first_pending.id,
            second_pending.id,
        }
        assert counts == [2, 2]

    unscoped = adapter.snapshot(now=200, strict=True)
    assert latest == unscoped
    assert counts == [4, 3]


def test_snapshots_without_a_scope_always_read_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(tmp_path, monkeypatch)
    write_event(tmp_path / "plans", edge_event("c" * 32))
    _append_pending_event("plan:202611/pending.md", created_at=100)
    counts = _count_snapshot_reads(monkeypatch)

    adapter.snapshot(now=200, strict=True)
    adapter.snapshot(now=200, strict=True)

    assert counts == [2, 2]


def test_nested_scopes_share_memo_and_clear_on_outer_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(tmp_path, monkeypatch)
    write_event(tmp_path / "plans", edge_event("d" * 32))
    _append_pending_event("plan:202611/pending.md", created_at=100)
    counts = _count_snapshot_reads(monkeypatch)

    with artifact_link_snapshot_memo():
        adapter.snapshot(now=200, strict=True)
        with artifact_link_snapshot_memo():
            adapter.snapshot(now=200, strict=True)
        adapter.snapshot(now=200, strict=True)
        assert counts == [1, 1]

    adapter.snapshot(now=200, strict=True)
    assert counts == [2, 2]


def test_preview_aggregate_uses_one_event_snapshot_and_keeps_all_row_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject
    from sase.sdd import _artifact_link_outbox_io as outbox_io
    from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    plans.mkdir()
    research.mkdir()
    with BeadProject.init(tmp_path / "beads") as beads:
        target = beads.create("Snapshot target", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key=PROJECT_KEY,
            sidecar_roots={"plan": plans, "research": research},
            beads_dir=beads.beads_dir,
        )
        legacy_row = make_row(
            source="plan:202611/legacy.md",
            relation="cites",
            target="research:legacy.md",
        )
        bead_row = make_row(
            source="agent:writer.athena.worker",
            relation="cites",
            target=f"bead:{target.id}",
        )
        store.upsert_row(legacy_row)
        store.upsert_row(bead_row)
        write_event(plans, edge_event("e" * 32, target="plan:202611/durable.md"))
        _append_pending_event("plan:202611/pending.md", created_at=100)

        snapshots = 0
        snapshot = ArtifactLinkStore.artifact_link_event_snapshot
        outbox_reads = 0
        read_records = outbox_io._read_outbox_records_unlocked

        def _count_snapshot(
            owner: ArtifactLinkStore,
            *args: object,
            **kwargs: object,
        ):  # type: ignore[no-untyped-def]
            nonlocal snapshots
            snapshots += 1
            return snapshot(owner, *args, **kwargs)

        def _count_records(path: Path, project_key: str):  # type: ignore[no-untyped-def]
            nonlocal outbox_reads
            outbox_reads += 1
            return read_records(path, project_key)

        monkeypatch.setattr(
            ArtifactLinkStore,
            "artifact_link_event_snapshot",
            _count_snapshot,
        )
        monkeypatch.setattr(outbox_io, "_read_outbox_records_unlocked", _count_records)

        aggregate = store.preview_aggregate()

    pairs = {(row["source_ref"], row["target_ref"]) for row in aggregate["rows"]}
    assert pairs == {
        (legacy_row["source_ref"], legacy_row["target_ref"]),
        (bead_row["source_ref"], bead_row["target_ref"]),
        ("plan:202608/a.md", "plan:202611/durable.md"),
        ("agent:reader.athena.worker", "plan:202611/pending.md"),
    }
    assert snapshots == 1
    assert outbox_reads == 1
