import json
import shutil
import threading
from pathlib import Path

import pytest

from sase.core import artifact_file_explicit as explicit_module
from sase.core.artifact_file_facade import (
    list_artifact_files,
    list_explicit_artifact_files,
    list_indexed_artifact_files,
    store_default_artifact_file,
    store_explicit_artifact_file,
)
from sase.core.artifact_file_types import artifact_file_from_dict as types_from_dict

from .helpers import agent_dir, write_json


def test_list_artifact_files_uses_indexed_media_when_persisted(
    tmp_path: Path,
) -> None:
    """When done.json marks artifacts as persisted, media comes from the
    JSONL index (and survive workspace deletion)."""

    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    image = workspace / "sdd" / "research" / "diagram.png"
    video = workspace / "renders" / "demo.mp4"
    image.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")

    artifact_files_root = tmp_path / ".sase" / "artifacts"
    index_path = artifact_files_root / "index.jsonl"
    stored_image = store_default_artifact_file(
        image,
        artifacts_dir,
        kind="image",
        artifact_files_root=artifact_files_root,
        workspace_dir=str(workspace),
    )
    stored_video = store_default_artifact_file(
        video,
        artifacts_dir,
        kind="file",
        artifact_files_root=artifact_files_root,
        workspace_dir=str(workspace),
    )
    assert stored_image is not None
    assert stored_video is not None

    write_json(
        artifacts_dir / "done.json",
        {
            "workspace_dir": str(workspace),
            "image_paths": [str(image)],
            "video_paths": [str(video)],
            "default_artifacts_persisted": True,
        },
    )

    # Workspace cleaned up, just like a recycled sase_<N> dir.
    shutil.rmtree(workspace)

    artifacts = list_artifact_files(artifacts_dir, index_path=index_path)
    rows_by_source = {
        a.source_path: a for a in artifacts if a.kind in {"image", "file"}
    }
    assert rows_by_source[str(image)].path == stored_image.path
    assert rows_by_source[str(image)].kind == "image"
    assert rows_by_source[str(video)].path == stored_video.path
    assert rows_by_source[str(video)].kind == "file"
    assert Path(rows_by_source[str(image)].path).is_file()
    assert Path(rows_by_source[str(video)].path).is_file()


def test_list_artifact_files_falls_back_to_legacy_synthesis_without_marker(
    tmp_path: Path,
) -> None:
    """Legacy agents (no ``default_artifacts_persisted`` marker) still get
    on-the-fly media synthesis from ``done.json``."""

    artifacts_dir = agent_dir(tmp_path)
    image = tmp_path / "legacy.png"
    video = tmp_path / "legacy.mp4"
    image.write_bytes(b"png")
    video.write_bytes(b"mp4")
    write_json(
        artifacts_dir / "done.json",
        {
            "image_paths": [str(image)],
            "video_paths": [str(video)],
        },
    )

    artifacts = list_artifact_files(
        artifacts_dir,
        index_path=tmp_path / ".sase" / "artifacts" / "index.jsonl",
    )
    assert [(a.kind, a.path) for a in artifacts] == [
        ("image", str(image)),
        ("file", str(video)),
    ]


def test_list_artifact_files_legacy_synthesis_includes_prompt_video(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    video = workspace / "clips" / "reference.m4v"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"m4v")
    write_json(artifacts_dir / "done.json", {"workspace_dir": str(workspace)})
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Reference clip: clips/reference.m4v\n",
        encoding="utf-8",
    )

    artifacts = list_artifact_files(
        artifacts_dir,
        index_path=tmp_path / ".sase" / "artifacts" / "index.jsonl",
    )

    assert [(artifact.kind, artifact.path) for artifact in artifacts] == [
        ("file", str(video.resolve()))
    ]


def test_list_indexed_artifact_files_returns_explicit_and_default_rows(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    explicit_source = tmp_path / "explicit.md"
    explicit_source.write_text("explicit", encoding="utf-8")
    default_source = tmp_path / "workspace" / "image.png"
    default_source.parent.mkdir(parents=True)
    default_source.write_bytes(b"png")

    artifact_files_root = tmp_path / ".sase" / "artifacts"
    index_path = artifact_files_root / "index.jsonl"
    store_explicit_artifact_file(
        explicit_source,
        artifacts_dir,
        label="Report",
        artifact_files_root=artifact_files_root,
    )
    store_default_artifact_file(
        default_source,
        artifacts_dir,
        artifact_files_root=artifact_files_root,
    )

    indexed = list_indexed_artifact_files(artifacts_dir, index_path=index_path)
    explicit = list_explicit_artifact_files(artifacts_dir, index_path=index_path)

    assert {a.label for a in indexed} == {"Report", "image.png"}
    assert {a.explicit for a in indexed} == {True, False}
    assert [a.label for a in explicit] == ["Report"]


def _envelope(
    artifact_id: str,
    *,
    dir_path: str,
    project: str | None,
    timestamp: str | None,
    explicit: bool = True,
    kind: str = "file",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    artifact: dict[str, object] = {
        "id": artifact_id,
        "label": artifact_id,
        "kind": kind,
        "path": f"/stored/{artifact_id}",
        "agent_artifacts_dir": dir_path,
        "project": project,
        "raw_timestamp": timestamp,
        "explicit": explicit,
        "agent_name": "agent.one",
    }
    if extra:
        artifact.update(extra)
    return {"schema_version": 2, "artifact": artifact}


def test_list_indexed_matches_association_fallback_not_agent_name(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    index_path = tmp_path / "index.jsonl"
    target = str(artifacts_dir)
    lines = [
        _envelope("exact", dir_path=target, project="proj", timestamp="20260507123456"),
        _envelope(
            "fallback",
            dir_path=str(tmp_path / "relocated"),
            project="proj",
            timestamp="20260507123456",
        ),
        _envelope(
            "same-name-other-run",
            dir_path=str(tmp_path / "other-run"),
            project="proj",
            timestamp="20260508000000",
        ),
        _envelope(
            "null-project",
            dir_path=str(tmp_path / "null-p"),
            project=None,
            timestamp="20260507123456",
        ),
        {
            "schema_version": 2,
            "artifact": {
                "id": "no-label",
                "kind": "file",
                "path": "/x",
                "agent_artifacts_dir": target,
            },
        },
        {
            "schema_version": 3,
            "artifact": {"id": "future", "label": "x", "kind": "file"},
        },
        "{malformed",
    ]
    index_path.write_text(
        "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines)
        + "\n",
        encoding="utf-8",
    )

    indexed = list_indexed_artifact_files(artifacts_dir, index_path=index_path)
    assert [row.id for row in indexed] == ["exact", "fallback"]


def test_list_indexed_constructs_only_matching_python_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    index_path = tmp_path / "index.jsonl"
    constructed: list[str] = []
    real = types_from_dict

    def counting(data: dict[str, object]) -> object:
        constructed.append(str(data["id"]))
        return real(data)

    monkeypatch.setattr(
        "sase.core.artifact_file_query_facade.artifact_file_from_dict",
        counting,
    )
    explicit_module._artifact_file_association_cache.clear()
    unrelated = json.dumps(
        _envelope(
            "unrelated",
            dir_path="/other",
            project="other",
            timestamp="1",
        )
    )
    matching = [
        json.dumps(
            _envelope(
                "keep-a",
                dir_path=str(artifacts_dir),
                project="proj",
                timestamp="20260507123456",
            )
        ),
        json.dumps(
            {
                "schema_version": 2,
                "artifact": {
                    "id": "keep-b",
                    "label": "keep-b",
                    "kind": "image",
                    "path": None,
                    "vcs_repo": "sase",
                    "vcs_sha": "a" * 40,
                    "vcs_relpath": "docs/b.png",
                    "agent_artifacts_dir": str(tmp_path / "moved"),
                    "project": "proj",
                    "raw_timestamp": "20260507123456",
                    "explicit": False,
                },
            }
        ),
    ]
    index_path.write_text(
        "\n".join([unrelated] * 50_000 + matching) + "\n", encoding="utf-8"
    )

    indexed = list_indexed_artifact_files(artifacts_dir, index_path=index_path)
    explicit = list_explicit_artifact_files(artifacts_dir, index_path=index_path)

    assert [row.id for row in indexed] == ["keep-a", "keep-b"]
    assert [row.id for row in explicit] == ["keep-a"]
    assert constructed == ["keep-a", "keep-b", "keep-a"]
    assert not hasattr(explicit_module, "_artifact_file_index_cache")
    resolved = str(index_path.resolve(strict=False))
    cached_rows = sum(
        len(entry.rows)
        for key, entry in explicit_module._artifact_file_association_cache.items()
        if key[0] == resolved
    )
    assert cached_rows <= 3


def test_list_indexed_survives_concurrent_readers(tmp_path: Path) -> None:
    artifacts_dir = agent_dir(tmp_path)
    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        json.dumps(
            _envelope(
                "keep",
                dir_path=str(artifacts_dir),
                project="proj",
                timestamp="20260507123456",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    results: list[list[str]] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            rows = list_indexed_artifact_files(artifacts_dir, index_path=index_path)
            results.append([row.id for row in rows])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert results == [["keep"]] * 8
