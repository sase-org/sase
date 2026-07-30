import hashlib
import json
from pathlib import Path

import pytest

from sase.core.artifact_file_facade import (
    ArtifactFile,
    artifact_file_from_dict,
    artifact_file_mime_type,
    artifact_file_to_dict,
    read_artifact_file_index,
    store_explicit_artifact_file,
)

from .helpers import agent_dir


def _old_artifact_data(path: Path, *, artifact_id: str = "default:old") -> dict:
    return {
        "id": artifact_id,
        "label": path.name,
        "kind": "file",
        "path": str(path),
        "explicit": False,
    }


def test_new_fields_round_trip_and_old_rows_default_to_none(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    artifact = ArtifactFile(
        id="explicit:new",
        label="Report",
        kind="markdown",
        path=str(path),
        sha256="abc123",
        size_bytes=42,
        mime_type="text/markdown",
    )

    assert artifact_file_from_dict(artifact_file_to_dict(artifact)) == artifact

    old = artifact_file_from_dict(_old_artifact_data(path))
    assert old.sha256 is None
    assert old.size_bytes is None
    assert old.mime_type is None


def test_vcs_backed_row_round_trips_without_coercing_null_path() -> None:
    artifact = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256="a" * 64,
        size_bytes=42,
        mime_type="text/markdown",
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/report.md",
    )

    restored = artifact_file_from_dict(artifact_file_to_dict(artifact))

    assert restored == artifact
    assert restored.path is None
    assert restored.is_vcs_backed


@pytest.mark.parametrize(
    "payload",
    [
        {"path": None},
        {"path": None, "vcs_repo": "sase"},
        {"path": None, "vcs_repo": "sase", "vcs_sha": "b" * 40},
    ],
)
def test_row_without_path_requires_complete_vcs_provenance(
    payload: dict[str, object],
) -> None:
    data = {
        "id": "default:invalid",
        "label": "Invalid",
        "kind": "file",
        **payload,
    }

    with pytest.raises(ValueError, match="stored path or complete VCS"):
        artifact_file_from_dict(data)


def test_reader_accepts_supported_schema_range(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    index_path = tmp_path / "index.jsonl"
    rows = [
        {
            "schema_version": 1,
            "artifact": _old_artifact_data(first, artifact_id="default:one"),
        },
        {
            "schema_version": 2,
            "artifact": _old_artifact_data(second, artifact_id="default:two"),
        },
        {
            "schema_version": 3,
            "artifact": _old_artifact_data(second, artifact_id="default:three"),
        },
    ]
    index_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    assert [row.id for row in read_artifact_file_index(index_path)] == [
        "default:one",
        "default:two",
    ]


def test_unknown_version_line_survives_upsert_verbatim(tmp_path: Path) -> None:
    artifacts_dir = agent_dir(tmp_path)
    source = tmp_path / "report.md"
    source.write_text("# report\n", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"
    index_path.parent.mkdir(parents=True)
    foreign_line = b'{ "schema_version": 3, "future": {"keep": [1, 2, 3]} }'
    index_path.write_bytes(foreign_line)

    store_explicit_artifact_file(
        source,
        artifacts_dir,
        artifact_files_root=index_path.parent,
    )

    assert index_path.read_bytes().endswith(foreign_line)
    assert len(read_artifact_file_index(index_path)) == 1


def test_mime_type_known_suffixes_are_deterministic() -> None:
    assert artifact_file_mime_type("report.MD") == "text/markdown"
    assert artifact_file_mime_type("image.PNG") == "image/png"
    assert artifact_file_mime_type("archive.no-such-mime") == (
        "application/octet-stream"
    )


def test_identical_files_from_two_agents_have_distinct_ids_and_equal_digests(
    tmp_path: Path,
) -> None:
    first_agent = agent_dir(tmp_path)
    second_agent = first_agent.with_name("20260507123457")
    second_agent.mkdir(parents=True)
    first_source = tmp_path / "one.bin"
    second_source = tmp_path / "two.bin"
    first_source.write_bytes(b"identical")
    second_source.write_bytes(b"identical")
    artifact_root = tmp_path / ".sase" / "artifacts"

    first = store_explicit_artifact_file(
        first_source,
        first_agent,
        artifact_files_root=artifact_root,
    )
    second = store_explicit_artifact_file(
        second_source,
        second_agent,
        artifact_files_root=artifact_root,
    )

    digest = hashlib.sha256(b"identical").hexdigest()
    assert first.id != second.id
    assert first.sha256 == second.sha256 == digest
