import shutil
from pathlib import Path

from sase.core.artifact_file_facade import (
    list_artifact_files,
    list_explicit_artifact_files,
    list_indexed_artifact_files,
    store_default_artifact_file,
    store_explicit_artifact_file,
)

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
