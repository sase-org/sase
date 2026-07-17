from pathlib import Path

from sase.core.artifact_file_facade import (
    persist_default_artifact_files,
    read_artifact_file_index,
)

from .helpers import agent_dir


def test_persist_default_artifact_files_unions_media_paths_and_xprompt(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    diff_image = workspace / "out" / "diff_image.png"
    prompt_image = workspace / "screenshots" / "before.png"
    video = workspace / "renders" / "demo.mp4"
    for path in (diff_image, prompt_image, video):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.suffix.encode())
    (artifacts_dir / "coder_prompt.md").write_text(
        "Use screenshots/before.png and a missing/absent.png\n",
        encoding="utf-8",
    )

    artifact_files_root = tmp_path / ".sase" / "artifacts"
    index_path = artifact_files_root / "index.jsonl"
    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(diff_image), str(workspace / "ghost.png")],
        video_paths=[str(video), str(workspace / "missing.mp4")],
        workspace_dir=str(workspace),
        artifact_files_root=artifact_files_root,
        index_path=index_path,
    )

    persisted_sources = sorted(a.source_path or "" for a in persisted)
    assert persisted_sources == sorted([str(diff_image), str(prompt_image), str(video)])
    kinds_by_source = {artifact.source_path: artifact.kind for artifact in persisted}
    assert kinds_by_source == {
        str(diff_image): "image",
        str(prompt_image): "image",
        str(video): "file",
    }
    for artifact in persisted:
        assert artifact.explicit is False
        assert Path(artifact.path).is_file()

    # Idempotent: rerun produces same set with no duplicate index rows.
    persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(diff_image)],
        video_paths=[str(video)],
        workspace_dir=str(workspace),
        artifact_files_root=artifact_files_root,
        index_path=index_path,
    )
    indexed = read_artifact_file_index(index_path)
    assert sorted(a.source_path or "" for a in indexed) == sorted(
        [str(diff_image), str(prompt_image), str(video)]
    )


def test_persist_default_artifact_files_persists_prompt_video_as_file(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    video = workspace / "references" / "input.mov"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mov")
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Use references/input.mov as the source clip.\n",
        encoding="utf-8",
    )
    artifact_files_root = tmp_path / ".sase" / "artifacts"

    persisted = persist_default_artifact_files(
        artifacts_dir,
        workspace_dir=str(workspace),
        artifact_files_root=artifact_files_root,
        index_path=artifact_files_root / "index.jsonl",
    )

    assert [
        (artifact.kind, artifact.source_path, artifact.label) for artifact in persisted
    ] == [("file", str(video.resolve()), "input.mov")]
    assert persisted[0].explicit is False
    assert Path(persisted[0].path).is_file()


def test_persist_default_artifact_files_dedupes_media_candidates_stably(
    tmp_path: Path,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    shared_image = workspace / "out" / "shared.gif"
    direct_video = workspace / "out" / "demo.mp4"
    prompt_video = workspace / "refs" / "reference.webm"
    for path in (shared_image, direct_video, prompt_video):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.suffix.encode())
    (artifacts_dir / "coder_prompt.md").write_text(
        "Compare out/shared.gif, out/demo.mp4, and refs/reference.webm.\n",
        encoding="utf-8",
    )
    artifact_files_root = tmp_path / ".sase" / "artifacts"

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(shared_image)],
        video_paths=[str(shared_image), str(direct_video)],
        workspace_dir=str(workspace),
        artifact_files_root=artifact_files_root,
        index_path=artifact_files_root / "index.jsonl",
    )

    assert [(artifact.source_path, artifact.kind) for artifact in persisted] == [
        (str(shared_image), "image"),
        (str(direct_video), "file"),
        (str(prompt_video.resolve()), "file"),
    ]
