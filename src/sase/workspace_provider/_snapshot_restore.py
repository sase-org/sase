"""Restore a verified checkout snapshot into a disposable clone."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

from sase.workspace_provider._rescue_store import RESCUE_MANIFEST_NAME
from sase.workspace_provider._snapshot_git import (
    git_output,
    require_git,
    run_git_bytes,
    safe_repo_path,
)
from sase.workspace_provider._snapshot_model import (
    SNAPSHOT_INDEX_STAGE_NAME,
    SNAPSHOT_KIND,
    SNAPSHOT_PACK_NAME,
    PreservationError,
    _DIR_OPERATION_MARKERS,
    _FILE_OPERATION_MARKERS,
)


def restore_git_snapshot(manifest_path: str | Path, dest: str | Path) -> None:
    """Load a verified snapshot into *dest* without touching the source.

    *dest* may be an empty directory (initialized as a git repo) or an
    existing clone. Restore uses only objects recorded in the snapshot pack.
    """
    manifest_file = Path(manifest_path)
    dest_repo = Path(dest)
    manifest = _load_manifest(manifest_file)
    rescue_dir = manifest_file.parent
    dest_repo.mkdir(parents=True, exist_ok=True)
    if not (dest_repo / ".git").exists() and not (dest_repo / ".git").is_file():
        require_git(
            run_git_bytes(dest_repo, "init", "-b", "main"),
            "git init",
        )
    _unpack_pack(dest_repo, rescue_dir / SNAPSHOT_PACK_NAME)
    head = str(manifest["head"])
    require_git(
        run_git_bytes(dest_repo, "update-ref", "HEAD", head),
        "git update-ref HEAD",
    )
    _clear_worktree(dest_repo)
    _materialize_tree(dest_repo, str(manifest["worktree_tree"]))
    _restore_index(dest_repo, manifest, rescue_dir)
    _restore_operation_markers(dest_repo, rescue_dir / "operation")


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    if manifest_path.name != RESCUE_MANIFEST_NAME:
        raise PreservationError(
            f"restore expected {RESCUE_MANIFEST_NAME}, got {manifest_path.name}"
        )
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreservationError(f"could not read snapshot manifest: {exc}") from exc
    if loaded.get("kind") != SNAPSHOT_KIND:
        raise PreservationError("manifest is not a verified snapshot")
    for key in ("head", "worktree_tree", "snapshot_id"):
        if not loaded.get(key):
            raise PreservationError(f"snapshot manifest missing {key}")
    return loaded


def _unpack_pack(dest_repo: Path, pack_path: Path) -> None:
    if not pack_path.is_file():
        raise PreservationError(f"snapshot pack is missing: {pack_path}")
    packed = pack_path.read_bytes()
    require_git(
        run_git_bytes(dest_repo, "unpack-objects", "-q", input_bytes=packed),
        "git unpack-objects",
    )


def _clear_worktree(dest_repo: Path) -> None:
    for child in dest_repo.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _materialize_tree(dest_repo: Path, tree: str) -> None:
    output = require_git(
        run_git_bytes(dest_repo, "ls-tree", "-r", "-z", "--full-tree", tree),
        f"git ls-tree {tree}",
    )
    for item in output.split(b"\0"):
        if not item:
            continue
        meta, path_b = item.split(b"\t", 1)
        parts = meta.split(b" ")
        if len(parts) < 3:
            raise PreservationError(f"malformed ls-tree row: {item!r}")
        mode = parts[0].decode("ascii")
        sha = parts[2].decode("ascii")
        rel = os.fsdecode(path_b)
        dest = safe_repo_path(dest_repo, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob = require_git(
            run_git_bytes(dest_repo, "cat-file", "blob", sha),
            f"git cat-file blob {sha}",
        )
        if dest.exists() or os.path.lexists(dest):
            dest.unlink()
        if mode == "120000":
            dest.symlink_to(os.fsdecode(blob))
            continue
        dest.write_bytes(blob)
        if mode == "100755":
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _restore_index(
    dest_repo: Path, manifest: dict[str, object], rescue_dir: Path
) -> None:
    require_git(
        run_git_bytes(dest_repo, "read-tree", "--empty"),
        "git read-tree --empty",
    )
    index_tree = manifest.get("index_tree")
    unmerged = bool(manifest.get("unmerged"))
    if isinstance(index_tree, str) and index_tree and not unmerged:
        require_git(
            run_git_bytes(dest_repo, "read-tree", index_tree),
            f"git read-tree {index_tree}",
        )
        return
    stage_path = rescue_dir / SNAPSHOT_INDEX_STAGE_NAME
    if not stage_path.is_file():
        raise PreservationError("index-stage payload is missing")
    require_git(
        run_git_bytes(
            dest_repo,
            "update-index",
            "-z",
            "--index-info",
            input_bytes=stage_path.read_bytes(),
        ),
        "git update-index --index-info",
    )


def _restore_operation_markers(dest_repo: Path, operation_dir: Path) -> None:
    if not operation_dir.is_dir():
        return
    git_dir = Path(git_output(dest_repo, "rev-parse", "--absolute-git-dir"))
    for name in _DIR_OPERATION_MARKERS:
        source = operation_dir / name
        if source.is_dir():
            target = git_dir / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, symlinks=True)
    for name in _FILE_OPERATION_MARKERS:
        source = operation_dir / name
        if source.is_file():
            shutil.copy2(source, git_dir / name)
