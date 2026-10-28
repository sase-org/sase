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
