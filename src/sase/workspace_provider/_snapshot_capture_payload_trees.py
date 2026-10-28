"""Worktree and index tree capture for verified snapshots."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sase.workspace_provider._snapshot_capture_common import is_managed_sidecar_rel
from sase.workspace_provider._snapshot_git import (
    file_mode_for_path,
    nested_git_root,
    read_worktree_bytes,
    require_git,
    run_git_bytes,
    safe_repo_path,
    snapshot_env,
    special_index_paths,
    status_paths,
)
from sase.workspace_provider._snapshot_model import (
    IndexEntry,
    PreservationError,
    SourceState,
)


def collect_worktree_entries(
    repo_root: Path,
    state: SourceState,
    *,
    env: dict[str, str],
) -> list[IndexEntry]:
    # Preserve index stage-0 content by default. Only read live files where Git's
    # status reports a change, where a conflict has non-zero stages, or where an
    # index flag makes status insufficient evidence.
    entries_by_path = {
        entry.path: IndexEntry(mode=entry.mode, sha=entry.sha, stage=0, path=entry.path)
        for entry in state.entries
        if entry.stage == 0 and not is_managed_sidecar_rel(entry.path)
    }
    candidate_paths = {
        rel for rel in status_paths(state.status_z) if not is_managed_sidecar_rel(rel)
    }
    candidate_paths.update(
        entry.path
        for entry in state.entries
        if entry.stage != 0 and not is_managed_sidecar_rel(entry.path)
    )
    candidate_paths.update(special_index_paths(repo_root, env=env))

    for rel in sorted(candidate_paths):
        entries_by_path.pop(rel, None)
        if is_managed_sidecar_rel(rel):
            continue
        path = safe_repo_path(repo_root, rel)
        if not path.exists() and not os.path.lexists(path):
            continue
        if path.is_dir() and not path.is_symlink():
            nested = nested_git_root(repo_root, rel)
            if nested is not None:
                if is_managed_sidecar_rel(nested.relative_to(repo_root).as_posix()):
                    continue
                raise PreservationError(
                    f"refusing to snapshot nested repository content: {nested}"
                )
            continue
        data = read_worktree_bytes(path)
        sha = _hash_blob(repo_root, data, env=env)
        entries_by_path[rel] = IndexEntry(
            mode=file_mode_for_path(path), sha=sha, stage=0, path=rel
        )
    return [entries_by_path[rel] for rel in sorted(entries_by_path)]


def _hash_blob(repo_root: Path, data: bytes, *, env: dict[str, str]) -> str:
    result = run_git_bytes(
        repo_root,
        "hash-object",
        "-w",
        "--stdin",
        "--no-filters",
        env=env,
        input_bytes=data,
    )
    sha = require_git(result, "git hash-object").strip().decode("ascii")
    if not sha:
        raise PreservationError("git hash-object returned an empty sha")
    return sha


def write_tree(
    repo_root: Path,
    entries: list[IndexEntry],
    *,
    object_dir: Path,
    alternate_dirs: tuple[Path, ...],
    tmp_index: Path,
) -> str:
    tmp_index.unlink(missing_ok=True)
    env = snapshot_env(
        index_file=tmp_index,
        object_dir=object_dir,
        alternate_dirs=alternate_dirs,
    )
    payload = b"".join(
        f"{entry.mode} {entry.sha} {entry.stage}\t".encode("ascii")
        + os.fsencode(entry.path)
        + b"\0"
        for entry in entries
    )
    require_git(
        run_git_bytes(
            repo_root,
            "update-index",
            "-z",
            "--index-info",
            env=env,
            input_bytes=payload,
        ),
        "git update-index --index-info",
    )
    sha = (
        require_git(
            run_git_bytes(repo_root, "write-tree", env=env),
            "git write-tree",
        )
        .strip()
        .decode("ascii")
    )
    if not sha:
        raise PreservationError("git write-tree returned an empty sha")
    return sha


def build_index_tree(
    repo_root: Path,
    state: SourceState,
    *,
    object_dir: Path,
    tmp_index: Path,
) -> str | None:
    if any(entry.stage != 0 for entry in state.entries):
        return None
    if not state.index_path.is_file():
        return None
    shutil.copyfile(state.index_path, tmp_index)
    env = snapshot_env(
        index_file=tmp_index,
        object_dir=object_dir,
        alternate_dirs=(state.object_dir,),
    )
    result = run_git_bytes(repo_root, "write-tree", env=env)
    if result.returncode != 0:
        raise PreservationError(
            f"git write-tree for the index failed: "
            f"{(result.stderr or result.stdout).decode('utf-8', 'replace').strip()}"
        )
    sha = result.stdout.strip().decode("ascii")
    return sha or None


__all__ = [
    "build_index_tree",
    "collect_worktree_entries",
    "write_tree",
]
