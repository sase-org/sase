"""Verified snapshot capture and restore tests."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider import _snapshot_capture as capture_module
from sase.workspace_provider._snapshot_model import SourceState
from sase.workspace_provider.snapshot import (
    PreservationError,
    SnapshotRecord,
    restore_git_snapshot,
    snapshot_git_repo,
)
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    redirect_state,
    rescue_entries,
    seed_remote_clone,
)


def _ls_stage(repo: Path) -> str:
    return git(repo, "ls-files", "-z", "--stage").stdout


def _worktree_map(repo: Path) -> dict[str, bytes]:
    mapping: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(repo, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(repo).as_posix()
            if path.is_symlink():
                mapping[rel] = b"symlink:" + os.fsencode(os.readlink(path))
            else:
                mapping[rel] = path.read_bytes()
    return mapping


def _index_bytes(repo: Path) -> bytes:
    git_dir = git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()
    index = Path(git_dir) / "index"
    return index.read_bytes() if index.is_file() else b""


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _source_probe(repo: Path) -> tuple[str, bytes, str, dict[str, bytes]]:
    return _head(repo), _index_bytes(repo), _ls_stage(repo), _worktree_map(repo)


def _assert_source_unchanged(
    repo: Path, before: tuple[str, bytes, str, dict[str, bytes]]
) -> None:
    assert _source_probe(repo) == before


def _make_dirty_wiring(clone: Path) -> None:
    commit_file(clone, "src/dispatch.py", "dispatch-base\n", "tracked wiring")
    git(clone, "push")
    (clone / "src" / "dispatch.py").write_text("dispatch-dirty\n", encoding="utf-8")
    (clone / "src" / "new_impl.py").write_text("untracked-impl\n", encoding="utf-8")


def _restore_dest(tmp_path: Path) -> Path:
    dest = tmp_path / "restore-dest"
    dest.mkdir()
    return dest


def _snapshot(
    clone: Path, workspace: Path, *, reason: str = "verified snapshot"
) -> SnapshotRecord | None:
    return snapshot_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason=reason,
    )


def test_snapshot_returns_none_when_checkout_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)

    assert _snapshot(clone, workspace, reason="clean") is None
    assert rescue_entries(home) == []
    assert notified == []


def test_snapshot_refuses_non_git_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, _clone, _remote = seed_remote_clone(tmp_path)
    empty = tmp_path / "not-a-repo"
    empty.mkdir()

    with pytest.raises(PreservationError, match="git"):
        snapshot_git_repo(
            empty,
            workspace_dir=workspace,
            workspace_num=7,
            label="plans",
            reason="not a repo",
        )


def test_snapshot_restores_tracked_and_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    (clone / "docs" / "naïve file.txt").parent.mkdir(parents=True, exist_ok=True)
    (clone / "docs" / "naïve file.txt").write_text("unusual\n", encoding="utf-8")
    before = _source_probe(clone)

    record = _snapshot(clone, workspace)
    assert record is not None
    assert record.manifest_path.is_absolute()
    assert record.manifest_path.is_file()
    manifest = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "verified-snapshot"
    assert manifest["snapshot_id"] == record.snapshot_id
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "src" / "dispatch.py").read_text(encoding="utf-8") == (
        "dispatch-dirty\n"
    )
    assert (dest / "src" / "new_impl.py").read_text(encoding="utf-8") == (
        "untracked-impl\n"
    )
    assert (dest / "docs" / "naïve file.txt").read_text(encoding="utf-8") == (
        "unusual\n"
    )
    assert "src/new_impl.py" not in git(dest, "ls-files").stdout
    assert "src/dispatch.py" in git(dest, "diff", "--name-only", "HEAD").stdout


def test_snapshot_restores_staged_only_and_distinct_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "tracked.txt", "head-bytes\n", "base tracked")
    git(clone, "push")
    (clone / "tracked.txt").write_text("staged-bytes\n", encoding="utf-8")
    git(clone, "add", "--", "tracked.txt")
    (clone / "tracked.txt").write_text("head-bytes\n", encoding="utf-8")
    staged_only = git(clone, "diff", "--cached", "--binary", "HEAD").stdout
    worktree_after_stage = (clone / "tracked.txt").read_text(encoding="utf-8")
    assert worktree_after_stage == "head-bytes\n"
    assert "staged-bytes" in staged_only
    before = _source_probe(clone)

    record = _snapshot(clone, workspace, reason="staged-only")
    assert record is not None
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "tracked.txt").read_text(encoding="utf-8") == "head-bytes\n"
    assert git(dest, "diff", "--cached", "--binary", "HEAD").stdout == staged_only

    (clone / "tracked.txt").write_text("unstaged-bytes\n", encoding="utf-8")
    distinct = _snapshot(clone, workspace, reason="distinct")
    assert distinct is not None
    dest2 = tmp_path / "restore-distinct"
    dest2.mkdir()
    restore_git_snapshot(distinct.manifest_path, dest2)
    assert (dest2 / "tracked.txt").read_text(encoding="utf-8") == "unstaged-bytes\n"
    assert "staged-bytes" in git(dest2, "diff", "--cached", "--binary", "HEAD").stdout
    assert "unstaged-bytes" in git(dest2, "diff", "--binary", "HEAD").stdout


def test_snapshot_restores_deletion_binary_and_tracked_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "keep.txt", "keep\n", "keep")
    commit_file(clone, "delete-me.txt", "gone-soon\n", "to delete")
    commit_file(clone, "build/out.bin", "tracked-ignored\n", "tracked build")
    git(clone, "push")
    (clone / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(clone, "add", "--", ".gitignore")
    git(clone, "commit", "-m", "ignore build")
    git(clone, "push")
    (clone / "delete-me.txt").unlink()
    git(clone, "add", "--", "delete-me.txt")
    (clone / "keep.txt").unlink()
    (clone / "build" / "out.bin").write_bytes(b"tracked-ignored-dirty\x00\xff")
    (clone / "payload.bin").write_bytes(b"\x00\xffbinary-untracked")
    before = _source_probe(clone)

    record = _snapshot(clone, workspace, reason="delete-binary-ignored")
    assert record is not None
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert not (dest / "keep.txt").exists()
    assert not (dest / "delete-me.txt").exists()
    assert "delete-me.txt" in git(dest, "diff", "--cached", "--name-only").stdout
    assert (dest / "build" / "out.bin").read_bytes() == b"tracked-ignored-dirty\x00\xff"
    assert (dest / "payload.bin").read_bytes() == b"\x00\xffbinary-untracked"
    mode = (dest / "build" / "out.bin").stat().st_mode
    assert not stat.S_ISDIR(mode)


def test_snapshot_restores_conflict_stages_and_worktree_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "file.txt", "base\n", "base file")
    git(clone, "checkout", "-b", "feature")
    commit_file(clone, "file.txt", "feature\n", "feature change")
    git(clone, "checkout", "-q", "main")
    commit_file(clone, "file.txt", "main\n", "main change")
    merge = subprocess.run(
        ["git", "merge", "feature"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
    conflict_bytes = (clone / "file.txt").read_bytes()
    stage_before = _ls_stage(clone)
    assert "file.txt" in stage_before
    before = _source_probe(clone)
    git_dir = Path(git(clone, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (git_dir / "MERGE_HEAD").is_file()

    record = _snapshot(clone, workspace, reason="conflict")
    assert record is not None
    assert record.unmerged is True
    _assert_source_unchanged(clone, before)

    dest = _restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "file.txt").read_bytes() == conflict_bytes
    dest_stage = git(dest, "ls-files", "--stage", "--", "file.txt").stdout
    src_stage = git(clone, "ls-files", "--stage", "--", "file.txt").stdout
    assert dest_stage == src_stage
    dest_git = Path(git(dest, "rev-parse", "--absolute-git-dir").stdout.strip())
    assert (dest_git / "MERGE_HEAD").is_file()


def test_snapshot_capture_failure_leaves_source_and_prior_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    first = _snapshot(clone, workspace, reason="first")
    assert first is not None
    first_manifest = first.manifest_path.read_text(encoding="utf-8")
    before = _source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected pack failure")

    monkeypatch.setattr(capture_module, "_write_pack", boom)
    with pytest.raises(PreservationError, match="injected pack failure"):
        _snapshot(clone, workspace, reason="second")
    _assert_source_unchanged(clone, before)
    assert first.rescue_dir.is_dir()
    assert first.manifest_path.read_text(encoding="utf-8") == first_manifest
    published = [
        entry for entry in rescue_entries(home) if (entry / "manifest.json").is_file()
    ]
    assert published == [first.rescue_dir]


def test_snapshot_manifest_failure_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    before = _source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected manifest failure")

    monkeypatch.setattr(capture_module, "publish_manifest", boom)
    with pytest.raises(PreservationError, match="injected manifest failure"):
        _snapshot(clone, workspace)
    _assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_size_cap_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    (clone / "src" / "dispatch.py").write_text("x" * 200, encoding="utf-8")
    before = _source_probe(clone)
    monkeypatch.setattr(capture_module, "SNAPSHOT_MAX_BYTES", 16)

    with pytest.raises(PreservationError, match="cap"):
        _snapshot(clone, workspace, reason="cap")
    _assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_detects_source_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    before = _source_probe(clone)
    original = capture_module.read_source_state
    calls = {"n": 0}

    def flipped(repo: Path) -> SourceState:
        calls["n"] += 1
        state = original(repo)
        if calls["n"] >= 2:
            (repo / "src" / "dispatch.py").write_text(
                "changed-during-capture\n", encoding="utf-8"
            )
            return original(repo)
        return state

    monkeypatch.setattr(capture_module, "read_source_state", flipped)
    with pytest.raises(PreservationError, match="changed during snapshot"):
        _snapshot(clone, workspace, reason="race")
    assert calls["n"] >= 2
    assert rescue_entries(home) == []
    assert (clone / "src" / "dispatch.py").read_text(encoding="utf-8") == (
        "changed-during-capture\n"
    )
    assert _head(clone) == before[0]
    assert _index_bytes(clone) == before[1]


def test_snapshot_ids_are_unique_for_same_head_and_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    _make_dirty_wiring(clone)
    first = _snapshot(clone, workspace, reason="one")
    second = _snapshot(clone, workspace, reason="two")
    assert first is not None and second is not None
    assert first.snapshot_id != second.snapshot_id
    assert first.rescue_dir != second.rescue_dir
    assert first.manifest_path != second.manifest_path
    assert first.rescue_dir.is_dir()
    assert second.rescue_dir.is_dir()
