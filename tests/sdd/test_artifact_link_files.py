"""Path-contract coverage for artifact-link indexes and lock sentinels."""

from __future__ import annotations

import json
from pathlib import Path

from sase.sdd._artifact_link_files import (
    ArtifactLinkRepoFileKind,
    artifact_link_lock_path,
    classify_artifact_link_repo_file,
)
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION


def _row(
    *,
    source: str = "agent:alice.athena.worker",
    relation: str = "read",
    target: str = "plan:202608/example.md",
    origin: str = "read",
) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": relation,
        "target_ref": target,
        "description": "Need the design context",
        "origin": origin,
        "created_by": "alice.athena.worker",
        "created_at": "2026-08-21T00:00:00Z",
        "uses": 1,
    }


def _write_index(
    repo: Path,
    artifact_ref: str,
    *,
    rows: list[dict[str, object]] | None = None,
    payload: dict[str, object] | None = None,
) -> Path:
    rel = artifact_ref.split(":", 1)[1]
    path = repo / "links" / f"{rel}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = payload or {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": artifact_ref,
        "rows": rows if rows is not None else [_row(target=artifact_ref)],
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def test_valid_new_and_modified_schema_v2_indexes(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    path = _write_index(repo, "plan:202608/example.md")

    assert (
        classify_artifact_link_repo_file(path, repo) is ArtifactLinkRepoFileKind.INDEX
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][0]["uses"] = 2
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert (
        classify_artifact_link_repo_file(path, repo) is ArtifactLinkRepoFileKind.INDEX
    )


def test_nested_artifact_paths_map_to_index_files(tmp_path: Path) -> None:
    repo = tmp_path / "research"
    repo.mkdir()
    path = _write_index(
        repo,
        "research:202608/nested/dir/report.md",
        rows=[
            _row(
                source="research:202608/nested/dir/report.md",
                relation="related",
                target="plan:202608/example.md",
                origin="manual",
            )
        ],
    )

    assert path == repo / "links" / "202608" / "nested" / "dir" / "report.md.json"
    assert (
        classify_artifact_link_repo_file(path, repo) is ArtifactLinkRepoFileKind.INDEX
    )


def test_path_ref_mismatch_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    path = _write_index(
        repo,
        "plan:202608/example.md",
        payload={
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "artifact_ref": "plan:202608/other.md",
            "rows": [_row(target="plan:202608/other.md")],
        },
    )

    assert (
        classify_artifact_link_repo_file(path, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )


def test_schema_v1_and_malformed_json_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    v1 = _write_index(
        repo,
        "plan:202608/legacy.md",
        payload={"schema_version": 1, "rows": []},
    )
    malformed = repo / "links" / "202608" / "broken.md.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text("{not-json", encoding="utf-8")

    assert (
        classify_artifact_link_repo_file(v1, repo) is ArtifactLinkRepoFileKind.REJECTED
    )
    assert (
        classify_artifact_link_repo_file(malformed, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )


def test_invalid_rows_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    path = _write_index(
        repo,
        "plan:202608/example.md",
        payload={
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "artifact_ref": "plan:202608/example.md",
            "rows": [{"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION}],
        },
    )

    assert (
        classify_artifact_link_repo_file(path, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )


def test_symlink_index_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    real = _write_index(repo, "plan:202608/example.md")
    link = repo / "links" / "202608" / "alias.md.json"
    link.symlink_to(real)

    assert (
        classify_artifact_link_repo_file(link, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )


def test_paired_zero_byte_lock_is_recognized(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    index = _write_index(repo, "plan:202608/example.md")
    lock = artifact_link_lock_path(index)
    lock.write_bytes(b"")

    assert lock == repo / "links" / "202608" / "example.md.lock"
    assert classify_artifact_link_repo_file(lock, repo) is ArtifactLinkRepoFileKind.LOCK


def test_nonempty_and_unpaired_locks_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    repo.mkdir()
    index = _write_index(repo, "plan:202608/example.md")
    nonempty = artifact_link_lock_path(index)
    nonempty.write_text("held\n", encoding="utf-8")
    unpaired = repo / "links" / "202608" / "missing.md.lock"
    unpaired.parent.mkdir(parents=True, exist_ok=True)
    unpaired.write_bytes(b"")

    assert (
        classify_artifact_link_repo_file(nonempty, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )
    assert (
        classify_artifact_link_repo_file(unpaired, repo)
        is ArtifactLinkRepoFileKind.REJECTED
    )


def test_markdown_outside_links_is_other(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    document = repo / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n", encoding="utf-8")

    assert (
        classify_artifact_link_repo_file(document, repo)
        is ArtifactLinkRepoFileKind.OTHER
    )
