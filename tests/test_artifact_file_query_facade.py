"""Tests for the Rust-backed artifact-file query facade."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.artifact_file_facade import read_artifact_file_index
from sase.core.artifact_file_query_facade import query_artifact_files


def _wire_row(
    artifact_id: str = "explicit:0123456789abcdef01234567",
    *,
    schema_version: int = 2,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "id": artifact_id,
        "label": "Report",
        "kind": "markdown",
        "path": "/stored/report.md",
        "source_path": "/source/report.md",
        "workspace_dir": "/workspace",
        "created_at": "2026-07-29T12:34:56Z",
        "agent_artifacts_dir": "/agents/run",
        "project": "gh_sase-org__sase",
        "workflow": "ace-run",
        "raw_timestamp": "20260729123456",
        "agent_name": "agent.one",
        "explicit": True,
        "sha256": "abc",
        "size_bytes": 3,
        "mime_type": "text/markdown",
    }


def test_query_checks_handshake_and_passes_complete_filter_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_require(name: str) -> Any:
        if name == "artifact_file_query_wire_schema_version":
            return lambda: 2
        if name == "artifact_files_query":

            def query(path: str, filters: dict[str, object]) -> list[object]:
                calls.append((path, filters))
                return [_wire_row()]

            return query
        raise AssertionError(name)

    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.require_rust_binding",
        fake_require,
    )
    index = tmp_path / ".." / tmp_path.name / "index.jsonl"

    rows = query_artifact_files(
        index,
        kinds=["image", "pdf"],
        project="project-key",
        agent="agent.one",
        since="14d",
        explicit_only=True,
        query="diagram",
        limit=7,
    )

    assert [row.id for row in rows] == ["explicit:0123456789abcdef01234567"]
    assert calls == [
        (
            str(index.expanduser().resolve(strict=False)),
            {
                "agent": "agent.one",
                "explicit_only": True,
                "kinds": ["image", "pdf"],
                "limit": 7,
                "project": "project-key",
                "query": "diagram",
                "since": "14d",
            },
        )
    ]


def test_query_rejects_stale_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.require_rust_binding",
        lambda _name: lambda: 1,
    )

    with pytest.raises(RuntimeError, match="expected 2, got 1"):
        query_artifact_files("/tmp/index.jsonl")


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"schema_version": 1}, "incomplete"),
        (_wire_row(schema_version=3), "unsupported"),
        ("not-an-object", "expected an object"),
    ],
)
def test_query_rejects_incompatible_rows(
    row: object,
    match: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(name: str) -> Any:
        if name == "artifact_file_query_wire_schema_version":
            return lambda: 2
        return lambda *_args: [row]

    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.require_rust_binding",
        fake_require,
    )

    with pytest.raises(RuntimeError, match=match):
        query_artifact_files("/tmp/index.jsonl")


def test_real_rust_query_matches_python_reader_for_v1_v2_fixture(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.jsonl"
    newest = _wire_row("explicit:111111111111111111111111", schema_version=2)
    newest["created_at"] = "2026-07-02T00:00:00Z"
    oldest = _wire_row("default:222222222222222222222222", schema_version=1)
    oldest["created_at"] = "2026-07-01T00:00:00Z"
    index.write_text(
        "\n".join(
            json.dumps(
                {
                    "schema_version": row["schema_version"],
                    "artifact": {
                        key: value
                        for key, value in row.items()
                        if key != "schema_version"
                    },
                }
            )
            for row in (newest, oldest)
        )
        + "\n",
        encoding="utf-8",
    )

    rust_rows = query_artifact_files(index)
    python_rows = read_artifact_file_index(index)

    assert rust_rows == python_rows


def test_query_accepts_complete_vcs_row_without_stored_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _wire_row()
    row.update(
        path=None,
        vcs_repo="sase",
        vcs_sha="b" * 40,
        vcs_relpath="docs/report.md",
    )

    def fake_require(name: str) -> Any:
        if name == "artifact_file_query_wire_schema_version":
            return lambda: 2
        return lambda *_args: [row]

    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.require_rust_binding",
        fake_require,
    )

    [artifact] = query_artifact_files("/tmp/index.jsonl")
    assert artifact.path is None
    assert artifact.is_vcs_backed


def test_query_rejects_partial_vcs_row_without_stored_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _wire_row()
    row.update(path=None, vcs_repo="sase")

    def fake_require(name: str) -> Any:
        if name == "artifact_file_query_wire_schema_version":
            return lambda: 2
        return lambda *_args: [row]

    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.require_rust_binding",
        fake_require,
    )

    with pytest.raises(RuntimeError, match="complete VCS provenance"):
        query_artifact_files("/tmp/index.jsonl")
