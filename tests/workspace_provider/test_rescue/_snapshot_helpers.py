"""Shared helpers for verified snapshot capture and restore tests."""

from __future__ import annotations

import os
from pathlib import Path

from sase.workspace_provider.snapshot import SnapshotRecord, snapshot_git_repo
from tests.workspace_provider.test_rescue._helpers import commit_file, git


def ls_stage(repo: Path) -> str:
    return git(repo, "ls-files", "-z", "--stage").stdout


def worktree_map(repo: Path) -> dict[str, bytes]:
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


def index_bytes(repo: Path) -> bytes:
    git_dir = git(repo, "rev-parse", "--absolute-git-dir").stdout.strip()
    index = Path(git_dir) / "index"
    return index.read_bytes() if index.is_file() else b""


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def source_probe(repo: Path) -> tuple[str, bytes, str, dict[str, bytes]]:
    return head(repo), index_bytes(repo), ls_stage(repo), worktree_map(repo)


def assert_source_unchanged(
    repo: Path, before: tuple[str, bytes, str, dict[str, bytes]]
) -> None:
    assert source_probe(repo) == before


def make_dirty_wiring(clone: Path) -> None:
    commit_file(clone, "src/dispatch.py", "dispatch-base\n", "tracked wiring")
    git(clone, "push")
    (clone / "src" / "dispatch.py").write_text("dispatch-dirty\n", encoding="utf-8")
    (clone / "src" / "new_impl.py").write_text("untracked-impl\n", encoding="utf-8")


def restore_dest(tmp_path: Path) -> Path:
    dest = tmp_path / "restore-dest"
    dest.mkdir()
    return dest


def snapshot(
    clone: Path, workspace: Path, *, reason: str = "verified snapshot"
) -> SnapshotRecord | None:
    return snapshot_git_repo(
        clone,
        workspace_dir=workspace,
        workspace_num=7,
        label="plans",
        reason=reason,
    )
