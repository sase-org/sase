import hashlib
import json
from pathlib import Path

from sase.core.artifact_file_facade import (
    backfill_artifact_file_index,
    inspect_artifact_file_index,
    read_artifact_file_index,
    verify_artifact_file_index,
)


def _envelope(
    path: Path | None,
    *,
    artifact_id: str,
    source_path: Path | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    mime_type: str | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "artifact": {
            "id": artifact_id,
            "label": "artifact" if path is None else path.name,
            "kind": "file",
            "path": None if path is None else str(path),
            "source_path": str(source_path) if source_path is not None else None,
            "explicit": False,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "mime_type": mime_type,
        },
    }


def _vcs_envelope(
    *,
    artifact_id: str,
    sha256: str,
) -> dict:
    row = _envelope(
        None,
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=4,
        mime_type="text/plain",
    )
    row["schema_version"] = 2
    row["artifact"].update(
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/report.txt",
    )
    row["artifact"]["label"] = "report.txt"
    return row


def _write_lines(index_path: Path, rows: list[dict | str]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        "".join(
            (row if isinstance(row, str) else json.dumps(row)) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def test_inspect_reports_enrichment_liveness_duplicates_and_foreign_rows(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live.txt"
    live.write_text("live", encoding="utf-8")
    missing = tmp_path / "missing.txt"
    missing_source = tmp_path / "gone-source.txt"
    index_path = tmp_path / "index.jsonl"
    _write_lines(
        index_path,
        [
            _envelope(
                live,
                artifact_id="default:duplicate",
                source_path=missing_source,
            ),
            _envelope(missing, artifact_id="default:duplicate"),
            '{"schema_version": 3, "artifact": {"id": "future"}}',
            "not-json",
        ],
    )

    report = inspect_artifact_file_index(index_path)

    assert report.total_rows == 4
    assert report.supported_rows == 2
    assert report.missing_enrichment_ids == (
        "default:duplicate",
        "default:duplicate",
    )
    assert report.missing_stored_path_ids == ("default:duplicate",)
    assert report.missing_source_path_ids == ("default:duplicate",)
    assert report.duplicate_ids == ("default:duplicate",)
    assert report.unrecognized_schema_versions == (3,)
    assert report.malformed_rows == 1


def test_backfill_is_idempotent_and_preserves_foreign_rows(tmp_path: Path) -> None:
    stored = tmp_path / "report.md"
    stored.write_bytes(b"# report\n")
    index_path = tmp_path / "index.jsonl"
    foreign_line = '{ "schema_version": 3, "future": true }'
    _write_lines(
        index_path,
        [
            _envelope(stored, artifact_id="default:report"),
            foreign_line,
        ],
    )

    first = backfill_artifact_file_index(index_path)
    after_first = index_path.read_bytes()
    second = backfill_artifact_file_index(index_path)

    assert first.changed is True
    assert first.updated_ids == ("default:report",)
    assert first.unrecognized_schema_versions == (3,)
    assert second.changed is False
    assert second.updated_ids == ()
    assert index_path.read_bytes() == after_first
    assert foreign_line.encode() + b"\n" in after_first
    [row] = read_artifact_file_index(index_path)
    assert row.sha256 == hashlib.sha256(b"# report\n").hexdigest()
    assert row.size_bytes == len(b"# report\n")
    assert row.mime_type == "text/markdown"


def test_backfill_never_guesses_fields_for_missing_stored_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.png"
    index_path = tmp_path / "index.jsonl"
    _write_lines(
        index_path,
        [_envelope(missing, artifact_id="default:missing")],
    )
    before = index_path.read_bytes()

    report = backfill_artifact_file_index(index_path)

    assert report.changed is False
    assert report.missing_stored_path_ids == ("default:missing",)
    assert index_path.read_bytes() == before


def test_verify_detects_tampered_stored_file(tmp_path: Path) -> None:
    stored = tmp_path / "artifact.bin"
    stored.write_bytes(b"original")
    original_digest = hashlib.sha256(b"original").hexdigest()
    index_path = tmp_path / "index.jsonl"
    _write_lines(
        index_path,
        [
            _envelope(
                stored,
                artifact_id="default:artifact",
                sha256=original_digest,
                size_bytes=len(b"original"),
                mime_type="application/octet-stream",
            )
        ],
    )
    stored.write_bytes(b"tampered")

    report = verify_artifact_file_index(index_path)

    assert report.verified_ids == ("default:artifact",)
    assert len(report.mismatches) == 1
    mismatch = report.mismatches[0]
    assert mismatch.id == "default:artifact"
    assert mismatch.expected_sha256 == original_digest
    assert mismatch.actual_sha256 == hashlib.sha256(b"tampered").hexdigest()


def test_vcs_rows_are_healthy_and_verify_by_materialization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    materialized = tmp_path / "cache" / "report.txt"
    materialized.parent.mkdir()
    materialized.write_bytes(b"live")
    digest = hashlib.sha256(b"live").hexdigest()
    index_path = tmp_path / "index.jsonl"
    _write_lines(
        index_path,
        [_vcs_envelope(artifact_id="default:vcs", sha256=digest)],
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.materialize_artifact_file",
        lambda _row, *, repositories: materialized,
    )

    inspection = inspect_artifact_file_index(index_path)
    backfill = backfill_artifact_file_index(index_path)
    verification = verify_artifact_file_index(index_path, repositories=())

    assert inspection.vcs_reference_rows == 1
    assert inspection.missing_stored_path_ids == ()
    assert inspection.vcs_provenance_incomplete_ids == ()
    assert backfill.changed is False
    assert backfill.missing_stored_path_ids == ()
    assert verification.verified_ids == ("default:vcs",)
    assert verification.unresolvable_vcs_ids == ()


def test_verify_reports_unresolvable_vcs_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "index.jsonl"
    _write_lines(
        index_path,
        [_vcs_envelope(artifact_id="default:missing-vcs", sha256="a" * 64)],
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.materialize_artifact_file",
        lambda _row, *, repositories: None,
    )

    report = verify_artifact_file_index(index_path, repositories=())

    assert report.unresolvable_vcs_ids == ("default:missing-vcs",)
    assert report.missing_stored_path_ids == ()


def test_inspect_names_byte_free_row_with_partial_vcs_provenance(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "index.jsonl"
    row = _vcs_envelope(artifact_id="default:partial-vcs", sha256="a" * 64)
    del row["artifact"]["vcs_relpath"]
    _write_lines(index_path, [row])

    report = inspect_artifact_file_index(index_path)

    assert report.supported_rows == 0
    assert report.vcs_provenance_incomplete_ids == ("default:partial-vcs",)
    assert report.malformed_rows == 1
