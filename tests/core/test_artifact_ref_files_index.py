from __future__ import annotations

from pathlib import Path

import sase_core_rs

from sase.core.artifact_ref_files_index import (
    query_ref_file_versions,
    upsert_ref_file_versions,
)


def _record(
    *,
    raw_ref: str = "@file:/tmp/gtd.md",
    logical_path: str | None = "bob:gtd.md",
    sha256: str = "a" * 64,
    recorded_at: str = "2026-08-01T00:00:00Z",
    origin: str | None = "ref",
) -> dict[str, object]:
    return {
        "raw_ref": raw_ref,
        "recorded_at": recorded_at,
        "source_path": "/tmp/gtd.md",
        "sha256": sha256,
        "size_bytes": 5,
        "mime_type": "text/markdown",
        "pool_relpath": "pool/captured.md",
        "logical_path": logical_path,
        "root_name": "bob",
        "authored_path": "/tmp/gtd.md",
        "origin": origin,
        "object_relpath": sase_core_rs.artifact_object_relpath(sha256),
    }


def test_upsert_and_fold_versions(tmp_path: Path) -> None:
    index = tmp_path / "ref-files.jsonl"
    unchanged = _record(sha256="a" * 64, recorded_at="2026-08-01T00:00:00Z")
    repeated = _record(sha256="a" * 64, recorded_at="2026-08-02T00:00:00Z")
    changed = _record(sha256="b" * 64, recorded_at="2026-08-03T00:00:00Z")

    assert (
        upsert_ref_file_versions(
            [unchanged, repeated, changed],
            index_path=index,
            agent_name="agent.one",
            project="sase",
            sidecar_repo="sase--agents",
        )
        == 3
    )

    [logical] = query_ref_file_versions(index_path=index)
    assert logical["logical_path"] == "bob:gtd.md"
    assert [version["sha256"] for version in logical["versions"]] == [
        "a" * 64,
        "b" * 64,
    ]
    assert logical["versions"][0]["agents"] == ["agent.one"]


def test_created_origin_row_carries_artifact_id_alias(tmp_path: Path) -> None:
    index = tmp_path / "ref-files.jsonl"
    row = _record(
        raw_ref="@file:explicit:52895d68931185056fd0e49f",
        logical_path=None,
        origin=None,
    )

    upsert_ref_file_versions([row], index_path=index)

    [logical] = query_ref_file_versions(index_path=index)
    assert logical["origin"] == "created"
    assert logical["versions"][0]["artifact_id"] == "explicit:52895d68931185056fd0e49f"
    assert logical["logical_path"] == "/tmp/gtd.md"


def test_query_skips_malformed_lines(tmp_path: Path) -> None:
    index = tmp_path / "ref-files.jsonl"
    valid = _record()
    rendered = sase_core_rs.artifact_ref_file_row_render(
        {
            "schema_version": sase_core_rs.artifact_ref_file_index_wire_schema_version(),
            "logical_path": "bob:gtd.md",
            "root_name": "bob",
            "authored_path": "/tmp/gtd.md",
            "artifact_id": None,
            "sha256": valid["sha256"],
            "size_bytes": 5,
            "mime_type": "text/markdown",
            "first_seen_at": "2026-08-01T00:00:00Z",
            "origin": "ref",
            "object_relpath": valid["object_relpath"],
            "sidecar_repo": None,
            "agents": [],
            "projects": [],
        }
    )
    index.write_text(f"not json\n{rendered}\n", encoding="utf-8")

    assert len(query_ref_file_versions(index_path=index)) == 1
