import hashlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

from sase._repo_inventory_models import RepoCloneRecord, RepoInventory, RepoRecord
from sase.core.artifact_capture_policy import CaptureLimits
from sase.core.artifact_file_facade import (
    persist_default_artifact_files,
    read_artifact_file_index,
    store_explicit_artifact_file,
)
from tests._sdd_commit_helpers import init_test_git_repo

from .helpers import agent_dir

PROJECT = "proj"
WORKSPACE_NUM = 7


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _init_pushed_repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    repo = tmp_path / "workspace"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    init_test_git_repo(repo)
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(bare))
    return repo


def _push_repo(repo: Path) -> str:
    _git(repo, "push", "-qu", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "-a")
    return _git(repo, "rev-parse", "HEAD")


def _install_inventory(monkeypatch: Any, repo: Path) -> None:
    clone = RepoCloneRecord(WORKSPACE_NUM, str(repo), True)
    record = RepoRecord(
        name=PROJECT,
        kind="primary",
        project=PROJECT,
        project_key=PROJECT,
        path=str(repo),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=(clone,),
    )
    monkeypatch.setattr(
        "sase.core.artifact_capture_policy.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((record,)),
    )


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_key(path: str | None) -> str:
    assert path is not None
    return str(Path(path).resolve(strict=False))


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


def test_persist_default_artifact_files_excludes_declared_sources(
    tmp_path: Path,
    capsys: Any,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    workspace = tmp_path / "workspace"
    declared = _write(workspace / "declared.png", b"declared")
    discovered = _write(workspace / "discovered.png", b"discovered")
    artifact_files_root = tmp_path / ".sase" / "artifacts"
    index_path = artifact_files_root / "index.jsonl"
    explicit = store_explicit_artifact_file(
        declared,
        artifacts_dir,
        artifact_files_root=artifact_files_root,
        index_path=index_path,
    )

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(declared), str(discovered)],
        workspace_dir=str(workspace),
        artifact_files_root=artifact_files_root,
        index_path=index_path,
        print_summary=True,
    )

    assert [row.source_path for row in persisted] == [str(discovered)]
    declared_rows = [
        row
        for row in read_artifact_file_index(index_path)
        if row.source_path == str(declared)
    ]
    assert declared_rows == [explicit]
    assert declared_rows[0].explicit is True
    assert capsys.readouterr().out.strip() == (
        "[artifacts] default capture: stored=1 referenced=0 skipped=0 "
        "declared=1 cap_fired=false"
    )


def test_persist_default_artifact_files_ignores_explicit_rows_without_source(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    image = _write(tmp_path / "workspace" / "image.png", b"image")
    artifact_files_root = tmp_path / ".sase" / "artifacts"
    monkeypatch.setattr(
        "sase.core.artifact_file_defaults.list_indexed_artifact_files",
        lambda *_args, **_kwargs: [SimpleNamespace(explicit=True, source_path=None)],
    )

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(image)],
        artifact_files_root=artifact_files_root,
        index_path=artifact_files_root / "index.jsonl",
    )

    assert [row.source_path for row in persisted] == [str(image)]


def test_persist_default_artifact_files_captures_when_index_read_fails(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    image = _write(tmp_path / "workspace" / "image.png", b"image")
    artifact_files_root = tmp_path / ".sase" / "artifacts"

    def fail_index_read(*_args: object, **_kwargs: object) -> list[object]:
        raise OSError("index unavailable")

    monkeypatch.setattr(
        "sase.core.artifact_file_defaults.list_indexed_artifact_files",
        fail_index_read,
    )

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(image)],
        artifact_files_root=artifact_files_root,
        index_path=artifact_files_root / "index.jsonl",
    )

    assert [row.source_path for row in persisted] == [str(image)]


def test_persist_default_artifact_files_applies_capture_policy_matrix(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    repo = _init_pushed_repo(tmp_path)
    clean = _write(repo / "clean.png", b"clean")
    dirty = _write(repo / "dirty.png", b"dirty-v1")
    mentioned_tracked = _write(repo / "mentioned.png", b"mentioned")
    _git(repo, "add", "clean.png", "dirty.png", "mentioned.png")
    _git(repo, "commit", "-qm", "seed")
    pushed_sha = _push_repo(repo)
    dirty.write_bytes(b"dirty-v2")
    untracked_changed = _write(repo / "untracked_changed.png", b"untracked-changed")
    mentioned_untracked = _write(repo / "mentioned_untracked.png", b"mentioned-skip")
    os.utime(mentioned_untracked, (1, 1))
    external = _write(tmp_path / "external.png", b"external")
    os.utime(external, (1, 1))
    (artifacts_dir / "raw_xprompt.md").write_text(
        f"Compare mentioned.png, mentioned_untracked.png, and {external}.\n",
        encoding="utf-8",
    )
    _install_inventory(monkeypatch, repo)
    artifact_files_root = tmp_path / ".sase" / "artifacts"
    index_path = artifact_files_root / "index.jsonl"

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(clean), str(dirty), str(untracked_changed)],
        workspace_dir=str(repo),
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        artifact_files_root=artifact_files_root,
        index_path=index_path,
    )

    by_source = {_source_key(row.source_path): row for row in persisted}
    assert set(by_source) == {
        str(clean),
        str(dirty),
        str(untracked_changed),
        str(mentioned_tracked.resolve()),
        str(external.resolve()),
    }
    assert str(mentioned_untracked.resolve()) not in by_source

    clean_row = by_source[str(clean)]
    mentioned_row = by_source[str(mentioned_tracked.resolve())]
    for row, relpath in ((clean_row, "clean.png"), (mentioned_row, "mentioned.png")):
        assert row.path is None
        assert row.is_vcs_backed
        assert (row.vcs_repo, row.vcs_sha, row.vcs_relpath) == (
            PROJECT,
            pushed_sha,
            relpath,
        )
        assert row.sha256 == _digest(Path(row.source_path or ""))

    copied_sources = {str(dirty), str(untracked_changed), str(external.resolve())}
    for source in copied_sources:
        row = by_source[source]
        assert row.path is not None
        assert Path(row.path).is_file()
        assert row.sha256 == _digest(Path(row.source_path or ""))

    indexed_ids = sorted(row.id for row in read_artifact_file_index(index_path))
    persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(clean), str(dirty), str(untracked_changed)],
        workspace_dir=str(repo),
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        artifact_files_root=artifact_files_root,
        index_path=index_path,
    )
    assert sorted(row.id for row in read_artifact_file_index(index_path)) == indexed_ids


def test_persist_default_artifact_files_enforces_store_cap(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    artifacts_dir = agent_dir(tmp_path)
    repo = _init_pushed_repo(tmp_path)
    _write(repo / "seed.txt", b"seed")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-qm", "seed")
    _push_repo(repo)
    _install_inventory(monkeypatch, repo)
    first = _write(tmp_path / "first.png", b"first")
    second = _write(tmp_path / "second.png", b"second")
    artifact_files_root = tmp_path / ".sase" / "artifacts"

    persisted = persist_default_artifact_files(
        artifacts_dir,
        image_paths=[str(first), str(second)],
        workspace_dir=str(repo),
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        artifact_files_root=artifact_files_root,
        index_path=artifact_files_root / "index.jsonl",
        capture_limits=CaptureLimits(max_stored_per_agent=1, max_history_scan=20),
    )

    assert [_source_key(row.source_path) for row in persisted] == [str(first)]
