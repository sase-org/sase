import json
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from sase.core import artifact_file_explicit as explicit_module
from sase.core.artifact_file_facade import (
    list_artifact_files,
    list_explicit_artifact_files,
    read_artifact_file_index,
    store_default_artifact_file,
    store_explicit_artifact_file,
)
from sase.core.artifact_file_explicit import (
    list_indexed_artifact_files,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_types import ArtifactFile

from .helpers import agent_dir, write_json


def test_explicit_plan_duplicate_does_not_add_second_plan_row(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    archived_plan = tmp_path / ".sase" / "plans" / "plan.md"
    sdd_plan = tmp_path / "workspace" / "sdd" / "plans" / "202605" / "plan.md"
    explicit_plan = tmp_path / "explicit-plan.md"
    for path in (archived_plan, sdd_plan, explicit_plan):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Plan\n", encoding="utf-8")
    write_json(
        artifacts_dir / "agent_meta.json",
        {
            "plan_path": str(archived_plan),
            "sdd_plan_path": str(sdd_plan),
            "plan_committed": True,
        },
    )
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    store_explicit_artifact_file(
        explicit_plan,
        artifacts_dir,
        label="Explicit plan",
        kind="plan",
        artifact_files_root=tmp_path / ".sase" / "artifacts",
    )
    artifacts = list_artifact_files(artifacts_dir, index_path=index_path)

    plans = [artifact for artifact in artifacts if artifact.kind == "plan"]
    assert [
        (artifact.label, artifact.path, artifact.explicit) for artifact in plans
    ] == [("plan.md", str(sdd_plan), False)]


def test_single_explicit_plan_is_kept_without_metadata_plan(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    first_plan = tmp_path / "first.md"
    second_plan = tmp_path / "second.md"
    for path in (first_plan, second_plan):
        path.write_text("# Plan\n", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    store_explicit_artifact_file(
        first_plan,
        artifacts_dir,
        label="First plan",
        kind="plan",
        artifact_files_root=tmp_path / ".sase" / "artifacts",
    )
    store_explicit_artifact_file(
        second_plan,
        artifacts_dir,
        label="Second plan",
        kind="plan",
        artifact_files_root=tmp_path / ".sase" / "artifacts",
    )

    artifacts = list_artifact_files(artifacts_dir, index_path=index_path)

    assert [(artifact.kind, artifact.label) for artifact in artifacts] == [
        ("plan", "First plan")
    ]


def test_store_explicit_artifact_creates_index_and_dedupes_display_order(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    explicit_source = tmp_path / "report.md"
    explicit_source.write_text("# Report\n", encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_text("png", encoding="utf-8")
    write_json(
        artifacts_dir / "done.json",
        {
            "response_path": str(explicit_source),
            "image_paths": [str(image)],
        },
    )

    stored = store_explicit_artifact_file(
        explicit_source,
        artifacts_dir,
        label="Report",
        artifact_files_root=tmp_path / ".sase" / "artifacts",
    )

    indexed = read_artifact_file_index(tmp_path / ".sase" / "artifacts" / "index.jsonl")
    artifacts = list_artifact_files(
        artifacts_dir,
        index_path=tmp_path / ".sase" / "artifacts" / "index.jsonl",
    )

    assert len(indexed) == 1
    assert indexed[0] == stored
    assert Path(stored.path).is_file()
    assert Path(stored.path).is_relative_to(tmp_path / ".sase" / "artifacts")
    assert [(artifact.kind, artifact.label) for artifact in artifacts] == [
        ("chat", "Chat transcript"),
        ("markdown", "Report"),
        ("image", "image.png"),
    ]


def test_read_artifact_file_index_reuses_parse_until_stat_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_a = agent_dir(tmp_path)
    artifacts_b = artifacts_a.parent / "20260507123500"
    artifacts_b.mkdir(parents=True)
    root = tmp_path / ".sase" / "artifacts"
    index_path = root / "index.jsonl"
    source_a = tmp_path / "alpha.md"
    source_b = tmp_path / "beta.md"
    source_a.write_text("# Alpha\n", encoding="utf-8")
    source_b.write_text("# Beta\n", encoding="utf-8")
    row_a = store_explicit_artifact_file(
        source_a,
        artifacts_a,
        label="Alpha",
        artifact_files_root=root,
    )
    row_b = store_explicit_artifact_file(
        source_b,
        artifacts_b,
        label="Beta",
        artifact_files_root=root,
    )
    explicit_module._artifact_file_index_cache.clear()
    parse_count = 0
    real_reader = explicit_module.read_artifact_file_index_document_unlocked

    def counting_reader(path: Path) -> tuple[list[ArtifactFile], list[str]]:
        nonlocal parse_count
        parse_count += 1
        return real_reader(path)

    monkeypatch.setattr(
        explicit_module,
        "read_artifact_file_index_document_unlocked",
        counting_reader,
    )

    assert list_indexed_artifact_files(artifacts_a, index_path=index_path) == [row_a]
    assert list_indexed_artifact_files(artifacts_b, index_path=index_path) == [row_b]
    assert parse_count == 1

    future_mtime_ns = index_path.stat().st_mtime_ns + 10_000_000_000
    import os as _os

    _os.utime(index_path, ns=(future_mtime_ns, future_mtime_ns))
    assert list_indexed_artifact_files(artifacts_a, index_path=index_path) == [row_a]
    assert list_indexed_artifact_files(artifacts_b, index_path=index_path) == [row_b]
    assert parse_count == 2


def test_read_artifact_file_index_returns_defensive_list(tmp_path: Path) -> None:
    artifacts_dir = agent_dir(tmp_path)
    root = tmp_path / ".sase" / "artifacts"
    index_path = root / "index.jsonl"
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    stored = store_explicit_artifact_file(
        source,
        artifacts_dir,
        label="Report",
        artifact_files_root=root,
    )
    explicit_module._artifact_file_index_cache.clear()

    first = read_artifact_file_index(index_path)
    first.clear()

    assert read_artifact_file_index(index_path) == [stored]


def test_artifact_file_index_write_invalidates_cache_when_stat_is_unchanged(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    root = tmp_path / ".sase" / "artifacts"
    index_path = root / "index.jsonl"
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    stored = store_explicit_artifact_file(
        source,
        artifacts_dir,
        label="Alpha",
        artifact_files_root=root,
    )
    explicit_module._artifact_file_index_cache.clear()
    assert read_artifact_file_index(index_path) == [stored]

    cached_stat = index_path.stat()
    replacement = replace(stored, label="Bravo")
    write_artifact_file_index_unlocked(index_path, [replacement])
    assert index_path.stat().st_size == cached_stat.st_size
    import os as _os

    _os.utime(
        index_path,
        ns=(cached_stat.st_atime_ns, cached_stat.st_mtime_ns),
    )

    assert read_artifact_file_index(index_path) == [replacement]


def test_store_explicit_artifact_file_preserves_jsonl_wire_format(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    source = tmp_path / "report.md"
    source.write_text("# Report\n", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    stored = store_explicit_artifact_file(
        source,
        artifacts_dir,
        artifact_files_root=index_path.parent,
        created_at="2026-07-17T12:00:00+00:00",
    )

    row = json.loads(index_path.read_text(encoding="utf-8"))
    assert row["schema_version"] == 2
    assert set(row) == {"schema_version", "artifact"}
    assert set(row["artifact"]) == {
        "agent_artifacts_dir",
        "agent_name",
        "created_at",
        "explicit",
        "id",
        "kind",
        "label",
        "path",
        "project",
        "raw_timestamp",
        "sha256",
        "size_bytes",
        "source_path",
        "mime_type",
        "workflow",
        "workspace_dir",
        "vcs_relpath",
        "vcs_repo",
        "vcs_sha",
    }
    assert row["artifact"]["agent_artifacts_dir"] == str(artifacts_dir)
    assert row["artifact"]["path"] == stored.path
    assert stored.sha256 == hashlib.sha256(b"# Report\n").hexdigest()
    assert stored.size_bytes == len(b"# Report\n")
    assert stored.mime_type == "text/markdown"


def test_explicit_artifact_association_survives_removed_and_restored_run_dir(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    source = tmp_path / "artifact.txt"
    source.write_text("data", encoding="utf-8")
    index_path = tmp_path / ".sase" / "artifacts" / "index.jsonl"

    stored = store_explicit_artifact_file(
        source,
        artifacts_dir,
        artifact_files_root=tmp_path / ".sase" / "artifacts",
        move=True,
    )
    shutil.rmtree(artifacts_dir)

    explicit = list_explicit_artifact_files(artifacts_dir, index_path=index_path)

    assert explicit == [stored]
    assert not source.exists()
    assert Path(stored.path).is_file()

    artifacts_dir.mkdir(parents=True)
    revived = list_artifact_files(artifacts_dir, index_path=index_path)

    assert revived == [stored]


def test_store_default_artifact_file_writes_index_row_with_source_path(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "sdd" / "research" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-bytes")

    stored = store_default_artifact_file(
        image,
        artifacts_dir,
        artifact_files_root=tmp_path / ".sase" / "artifacts",
        workspace_dir=str(workspace),
    )

    assert stored is not None
    assert stored.explicit is False
    assert stored.source_path == str(image)
    assert stored.workspace_dir == str(workspace)
    assert stored.sha256 == hashlib.sha256(b"png-bytes").hexdigest()
    assert stored.size_bytes == len(b"png-bytes")
    assert stored.mime_type == "image/png"
    assert Path(stored.path).is_file()
    assert Path(stored.path).is_relative_to(tmp_path / ".sase" / "artifacts")

    indexed = read_artifact_file_index(tmp_path / ".sase" / "artifacts" / "index.jsonl")
    assert indexed == [stored]


def test_store_default_artifact_file_returns_none_for_missing_source(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    result = store_default_artifact_file(
        tmp_path / "does-not-exist.png",
        artifacts_dir,
        artifact_files_root=tmp_path / ".sase" / "artifacts",
    )
    assert result is None
    indexed = read_artifact_file_index(tmp_path / ".sase" / "artifacts" / "index.jsonl")
    assert indexed == []
