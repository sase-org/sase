from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.artifact_file_economics import (
    ArtifactFileEconomicsGroup,
    _ArtifactFileGenerationProjection,
    artifact_file_store_economics,
)
from sase.core.artifact_file_explicit import write_artifact_file_index_unlocked
from sase.core.artifact_file_types import ArtifactFile


def _rows(tmp_path: Path) -> list[ArtifactFile]:
    workspace = tmp_path / "workspace"
    return [
        ArtifactFile(
            id="explicit:111111111111111111111111",
            label="report",
            kind="markdown",
            path=str(tmp_path / "explicit.md"),
            created_at="2026-07-01T00:00:00Z",
            project="p",
            agent_name="explicit-agent",
            explicit=True,
            sha256="duplicate",
            size_bytes=100,
        ),
        ArtifactFile(
            id="default:222222222222222222222222",
            label="report",
            kind="image",
            path=str(tmp_path / "first.png"),
            source_path=str(workspace / "first.png"),
            workspace_dir=str(workspace),
            created_at="2026-07-02T00:00:00Z",
            project="p",
            agent_name="small-agent",
            sha256="duplicate",
            size_bytes=100,
        ),
        ArtifactFile(
            id="default:333333333333333333333333",
            label="report",
            kind="image",
            path=str(tmp_path / "second.png"),
            source_path=str(workspace / "second.png"),
            workspace_dir=str(workspace),
            created_at="2026-07-03T00:00:00Z",
            project="p",
            agent_name="large-agent",
            sha256="unique",
            size_bytes=200,
        ),
        ArtifactFile(
            id="default:444444444444444444444444",
            label="byte-free",
            kind="file",
            path=None,
            created_at="2026-07-04T00:00:00Z",
            project="q",
            agent_name="vcs-agent",
            sha256="vcs",
            size_bytes=50,
            vcs_repo="repo",
            vcs_sha="commit",
            vcs_relpath="path.txt",
        ),
    ]


def test_economics_validates_and_projects_every_core_field(tmp_path: Path) -> None:
    index_path = tmp_path / "index.jsonl"
    write_artifact_file_index_unlocked(index_path, _rows(tmp_path))

    result = artifact_file_store_economics(index_path=index_path, top_n=2)

    assert result.schema_version == 1
    assert (
        result.total_rows,
        result.explicit_rows,
        result.automatic_rows,
        result.vcs_backed_rows,
        result.rows_missing_size,
    ) == (4, 1, 3, 1, 0)
    assert (
        result.total_bytes,
        result.explicit_bytes,
        result.automatic_bytes,
        result.vcs_backed_bytes,
    ) == (450, 100, 350, 50)
    assert result.by_kind == (
        ArtifactFileEconomicsGroup("image", 2, 300),
        ArtifactFileEconomicsGroup("markdown", 1, 100),
        ArtifactFileEconomicsGroup("file", 1, 50),
    )
    assert result.by_project == (
        ArtifactFileEconomicsGroup("p", 3, 400),
        ArtifactFileEconomicsGroup("q", 1, 50),
    )
    assert result.by_agent == (
        ArtifactFileEconomicsGroup("large-agent", 1, 200),
        ArtifactFileEconomicsGroup("explicit-agent", 1, 100),
    )
    assert result.by_agent_truncated_groups == 2
    assert result.by_agent_truncated_bytes == 150
    assert result.first_created_at == "2026-07-01T00:00:00Z"
    assert result.last_created_at == "2026-07-04T00:00:00Z"
    assert result.window_days == 4
    assert result.bytes_per_day == 112.5
    assert result.rows_per_day == 1.0
    assert result.duplicate_digest_groups == 1
    assert result.redundant_digest_rows == 1
    assert result.redundant_digest_bytes == 100
    assert result.distinct_labels == 2
    assert result.label_generation_projections == (
        _ArtifactFileGenerationProjection(1, 1, 100),
        _ArtifactFileGenerationProjection(3, 0, 0),
        _ArtifactFileGenerationProjection(5, 0, 0),
    )
    assert result.source_inside_workspace_rows == 2
    assert result.source_inside_workspace_bytes == 300
    assert result.to_json_dict()["total_rows"] == 4


def test_economics_names_an_incompatible_binding_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def binding(name: str):  # type: ignore[no-untyped-def]
        if name == "artifact_file_lifecycle_wire_schema_version":
            return lambda: 1
        return lambda *_args: {"schema_version": 1}

    monkeypatch.setattr(
        "sase.core.artifact_file_economics.require_rust_binding",
        binding,
    )

    with pytest.raises(RuntimeError, match="total_rows"):
        artifact_file_store_economics(index_path="/missing")
