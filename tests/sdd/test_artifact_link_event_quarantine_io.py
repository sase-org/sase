"""Quarantine-record and local-admission IO tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import ArtifactLinkEventCorruptionError
from sase.sdd._artifact_link_event_collision import candidate_from_event
from sase.sdd._artifact_link_event_install import install_artifact_link_bytes
from sase.sdd._artifact_link_event_quarantine import (
    admission_sequence_for,
    attach_admission_evidence,
    load_artifact_link_quarantine_records,
    persist_artifact_link_quarantine_record,
    record_artifact_link_admission,
)
from sase.sdd._artifact_link_event_store import reduce_artifact_link_event_inputs
from tests.sdd._artifact_link_event_store_test_helpers import edge_event


def _canonical_json(event: dict[str, object]) -> str:
    return str(require_rust_binding("artifact_link_event_canonical_json")(event))


def _colliding_events() -> tuple[dict[str, object], dict[str, object]]:
    created_at = "2026-09-09T12:00:00Z"
    return (
        edge_event(
            "a" * 32,
            target="plan:202608/original.md",
            description="original payload",
            created_at=created_at,
        ),
        edge_event(
            "a" * 32,
            target="plan:202608/replay.md",
            description="replay payload",
            created_at=created_at,
        ),
    )


def test_persist_quarantine_record_is_idempotent_for_identical_bytes(
    tmp_path: Path,
) -> None:
    first, second = _colliding_events()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    relative = persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )

    assert relative.startswith("link-events/quarantine/v1/")
    assert (tmp_path / relative).is_file()
    persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    records = list((tmp_path / "link-events" / "quarantine" / "v1").rglob("*.json"))
    assert len(records) == 1
    loaded, errors = load_artifact_link_quarantine_records((tmp_path,))
    assert errors == ()
    assert len(loaded) == 1
    assert loaded[0].operation_id == finding.operation_id
    assert loaded[0].rejected_digest == finding.rejected_digest
    assert loaded[0].accepted_digest == finding.accepted_digest
    assert loaded[0].record_path == relative


def test_existing_quarantine_record_with_different_bytes_is_corruption(
    tmp_path: Path,
) -> None:
    first, second = _colliding_events()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    relative = persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )

    with pytest.raises(ArtifactLinkEventCorruptionError, match="different bytes"):
        install_artifact_link_bytes(tmp_path, relative, b'{"nope":true}\n')


def test_malformed_quarantine_record_is_a_blocking_load_error(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path / "link-events" / "quarantine" / "v1" / ("a" * 32) / f"{'b' * 64}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    findings, errors = load_artifact_link_quarantine_records((tmp_path,))

    assert findings == ()
    assert errors
    assert "not json" in errors[0] or "JSON" in errors[0] or "Expecting" in errors[0]


def test_admission_sequence_assigns_monotonic_first_wins_values(
    tmp_path: Path,
) -> None:
    first = record_artifact_link_admission(
        tmp_path,
        digest="a" * 64,
        operation_id="b" * 32,
    )
    second = record_artifact_link_admission(
        tmp_path,
        digest="c" * 64,
        operation_id="d" * 32,
    )
    again = record_artifact_link_admission(
        tmp_path,
        digest="a" * 64,
        operation_id="b" * 32,
    )

    assert first == 1
    assert second == 2
    assert again == 1
    assert admission_sequence_for(tmp_path, "a" * 64) == 1
    assert admission_sequence_for(tmp_path, "c" * 64) == 2


def test_attach_admission_evidence_fills_local_sequences(
    tmp_path: Path,
) -> None:
    event = edge_event("a" * 32)
    digest = str(require_rust_binding("artifact_link_event_digest")(event))
    record_artifact_link_admission(
        tmp_path,
        digest=digest,
        operation_id="a" * 32,
    )
    candidate = candidate_from_event(
        event,
        tier="durable",
        root=str(tmp_path),
        digest=digest,
    )

    [updated] = attach_admission_evidence((candidate,))

    assert updated.evidence.admission_sequence == 1


def _persist_finding(tmp_path: Path):
    first, second = _colliding_events()
    snapshot = reduce_artifact_link_event_inputs(
        durable_events=(first, second),
        strict=True,
    )
    finding = snapshot.quarantine_findings[0]
    relative = persist_artifact_link_quarantine_record(
        tmp_path,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    return finding, relative


def test_load_rejects_namespace_symlink_to_outside_record(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    store = tmp_path / "store"
    outside.mkdir()
    store.mkdir()
    finding, relative = _persist_finding(outside)
    outside_bytes = (outside / relative).read_bytes()
    namespace = store / "link-events" / "quarantine"
    namespace.mkdir(parents=True)
    (namespace / "v1").symlink_to(outside / "link-events" / "quarantine" / "v1")

    findings, errors = load_artifact_link_quarantine_records((store,))

    assert findings == ()
    assert any("symlink" in error for error in errors)
    assert (outside / relative).read_bytes() == outside_bytes
    with pytest.raises(ArtifactLinkEventCorruptionError, match="symlink"):
        persist_artifact_link_quarantine_record(
            store,
            finding,
            rejected_canonical_json=_canonical_json(finding.rejected_event),
        )
    assert (outside / relative).read_bytes() == outside_bytes


def test_load_and_persist_reject_operation_dir_and_leaf_symlinks(
    tmp_path: Path,
) -> None:
    finding, relative = _persist_finding(tmp_path)
    record_path = tmp_path / relative
    payload = record_path.read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(payload)

    record_path.unlink()
    record_path.symlink_to(outside)
    findings, errors = load_artifact_link_quarantine_records((tmp_path,))
    assert findings == ()
    assert any("symlink" in error for error in errors)
    with pytest.raises(ArtifactLinkEventCorruptionError, match="symlink"):
        persist_artifact_link_quarantine_record(
            tmp_path,
            finding,
            rejected_canonical_json=_canonical_json(finding.rejected_event),
        )

    record_path.unlink()
    op_dir = record_path.parent
    relocated = tmp_path / "relocated-op"
    relocated.mkdir()
    (relocated / record_path.name).write_bytes(payload)
    op_dir.rmdir()
    op_dir.symlink_to(relocated)
    findings, errors = load_artifact_link_quarantine_records((tmp_path,))
    assert findings == ()
    assert any("symlink" in error for error in errors)


def test_load_rejects_broken_namespace_symlink(tmp_path: Path) -> None:
    namespace = tmp_path / "link-events" / "quarantine"
    namespace.mkdir(parents=True)
    (namespace / "v1").symlink_to(tmp_path / "missing-target")

    findings, errors = load_artifact_link_quarantine_records((tmp_path,))

    assert findings == ()
    assert any("symlink" in error for error in errors)


def test_symlinked_store_root_ancestor_is_accepted(tmp_path: Path) -> None:
    real = tmp_path / "real-store"
    linked = tmp_path / "linked-store"
    real.mkdir()
    linked.symlink_to(real)
    finding, relative = _persist_finding(linked)

    findings, errors = load_artifact_link_quarantine_records((linked,))
    assert errors == ()
    assert len(findings) == 1
    assert (real / relative).is_file()
    assert not (real / relative).is_symlink()
    again = persist_artifact_link_quarantine_record(
        linked,
        finding,
        rejected_canonical_json=_canonical_json(finding.rejected_event),
    )
    assert again == relative


def test_load_rejects_operation_plain_file(tmp_path: Path) -> None:
    root = tmp_path / "store"
    namespace = root / "link-events" / "quarantine" / "v1"
    namespace.mkdir(parents=True)
    operation = namespace / ("a" * 32)
    operation.write_text("not a directory", encoding="utf-8")
    before = operation.read_bytes()

    findings, errors = load_artifact_link_quarantine_records((root,))

    assert findings == ()
    assert any("not a directory" in error for error in errors)
    assert operation.read_bytes() == before


def test_load_rejects_operation_broken_symlink(tmp_path: Path) -> None:
    root = tmp_path / "store"
    namespace = root / "link-events" / "quarantine" / "v1"
    namespace.mkdir(parents=True)
    (namespace / ("a" * 32)).symlink_to(tmp_path / "missing-target")

    findings, errors = load_artifact_link_quarantine_records((root,))

    assert findings == ()
    assert any("broken" in error for error in errors)


def test_load_rejects_staging_plain_file_and_broken_symlink(
    tmp_path: Path,
) -> None:
    for shape in ("plain-file", "broken-symlink"):
        root = tmp_path / f"store-{shape}"
        namespace = root / "link-events" / "quarantine" / "v1"
        namespace.mkdir(parents=True)
        staging = namespace / ".staging"
        if shape == "plain-file":
            staging.write_text("not a directory", encoding="utf-8")
        else:
            staging.symlink_to(tmp_path / "missing-target")
        findings, errors = load_artifact_link_quarantine_records((root,))
        assert findings == (), shape
        assert errors, shape
        assert any(
            "not a directory" in error or "broken" in error for error in errors
        ), shape


def test_persist_rejects_staging_symlink_without_outside_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd import _artifact_link_event_install as install_module

    root = tmp_path / "store"
    namespace = root / "link-events" / "quarantine" / "v1"
    namespace.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (namespace / ".staging").symlink_to(outside, target_is_directory=True)

    finding, _ = _persist_finding(tmp_path / "other")
    writes: list[str] = []
    real_open = install_module.os.open

    def observe_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if flags & install_module.os.O_CREAT:
            try:
                resolved = str((Path(path).resolve(strict=False)).relative_to(tmp_path))
            except ValueError:
                resolved = str(path)
            writes.append(resolved)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(install_module.os, "open", observe_open)
    with pytest.raises(ArtifactLinkEventCorruptionError, match="staging|symlink"):
        persist_artifact_link_quarantine_record(
            root,
            finding,
            rejected_canonical_json=_canonical_json(finding.rejected_event),
        )
    assert writes == []
    assert list(outside.iterdir()) == []
    assert not (root / "link-events" / "quarantine" / "v1" / ("a" * 32)).exists()


def test_persist_rejects_staging_plain_file(tmp_path: Path) -> None:
    root = tmp_path / "store"
    namespace = root / "link-events" / "quarantine" / "v1"
    namespace.mkdir(parents=True)
    (namespace / ".staging").write_text("not a directory", encoding="utf-8")
    finding, _ = _persist_finding(tmp_path / "other")

    with pytest.raises(ArtifactLinkEventCorruptionError, match="not a directory"):
        persist_artifact_link_quarantine_record(
            root,
            finding,
            rejected_canonical_json=_canonical_json(finding.rejected_event),
        )
