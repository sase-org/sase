from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

import sase.workspace_provider as workspace_provider
from sase.workspace_provider.snapshot import restore_git_snapshot
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    init_repo,
    redirect_state,
    seed_remote_clone,
)
from tests.workspace_provider.test_rescue._snapshot_helpers import (
    head,
    restore_dest,
    snapshot,
    worktree_map,
    ls_stage,
)

payload_trees_module = workspace_provider._snapshot_capture_payload_trees


def test_snapshot_hashes_only_dirty_candidates_in_a_large_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    for index in range(300):
        path = clone / "tracked" / f"{index:03}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"clean {index}\n", encoding="utf-8")
    git(clone, "add", "--", "tracked")
    git(clone, "commit", "-m", "many clean files")
    git(clone, "push")
    (clone / "tracked" / "100.txt").write_text("one dirty file\n", encoding="utf-8")

    hash_object_calls: list[tuple[str, ...]] = []
    real_run_git_bytes = payload_trees_module.run_git_bytes

    def count_hash_objects(
        repo: Path, *args: str, **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        if args and args[0] == "hash-object":
            hash_object_calls.append(args)
        return real_run_git_bytes(repo, *args, **kwargs)

    monkeypatch.setattr(payload_trees_module, "run_git_bytes", count_hash_objects)
    record = snapshot(clone, workspace, reason="hash only dirty candidate")
    assert record is not None
    assert len(hash_object_calls) <= 2


def test_snapshot_captures_assume_unchanged_and_skip_worktree_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    commit_file(clone, "assume.txt", "assume base\n", "assume base")
    commit_file(clone, "skip.txt", "skip base\n", "skip base")
    git(clone, "push")
    git(clone, "update-index", "--assume-unchanged", "assume.txt")
    git(clone, "update-index", "--skip-worktree", "skip.txt")
    (clone / "assume.txt").write_text("assume dirty\n", encoding="utf-8")
    (clone / "skip.txt").write_text("skip dirty\n", encoding="utf-8")

    record = snapshot(clone, workspace, reason="special index flags")
    assert record is not None
    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "assume.txt").read_text(encoding="utf-8") == "assume dirty\n"
    assert (dest / "skip.txt").read_text(encoding="utf-8") == "skip dirty\n"


def test_snapshot_excludes_gitlink_commits_from_pack_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    submodule = tmp_path / "submodule"
    init_repo(submodule)
    submodule_sha = head(submodule)
    clone = tmp_path / "superproject"
    init_repo(clone)
    commit_file(clone, "tracked.txt", "base\n", "tracked base")
    git(clone, "update-index", "--add", "--cacheinfo", f"160000,{submodule_sha},module")
    git(clone, "commit", "-m", "record gitlink")
    (clone / "tracked.txt").write_text("working edit\n", encoding="utf-8")

    record = snapshot(clone, workspace, reason="gitlink preservation")
    assert record is not None
    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "tracked.txt").read_text(encoding="utf-8") == "working edit\n"
    assert (
        git(dest, "ls-files", "--stage", "--", "module").stdout
        == git(clone, "ls-files", "--stage", "--", "module").stdout
    )
    assert not (dest / "module").exists()


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
    before = source_probe(clone)

    record = snapshot(clone, workspace, reason="staged-only")
    assert record is not None
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert (dest / "tracked.txt").read_text(encoding="utf-8") == "head-bytes\n"
    assert git(dest, "diff", "--cached", "--binary", "HEAD").stdout == staged_only

    (clone / "tracked.txt").write_text("unstaged-bytes\n", encoding="utf-8")
    distinct = snapshot(clone, workspace, reason="distinct")
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
    before = source_probe(clone)

    record = snapshot(clone, workspace, reason="delete-binary-ignored")
    assert record is not None
    assert_source_unchanged(clone, before)

    dest = restore_dest(tmp_path)
    restore_git_snapshot(record.manifest_path, dest)
    assert not (dest / "keep.txt").exists()
    assert not (dest / "delete-me.txt").exists()
    assert "delete-me.txt" in git(dest, "diff", "--cached", "--name-only").stdout
    assert (dest / "build" / "out.bin").read_bytes() == b"tracked-ignored-dirty\x00\xff"
    assert (dest / "payload.bin").read_bytes() == b"\x00\xffbinary-untracked"
    mode = (dest / "build" / "out.bin").stat().st_mode
    assert not stat.S_ISDIR(mode)
