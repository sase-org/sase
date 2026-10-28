"""Capture trees, packs, and manifests into a rescue directory."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from sase.workspace_provider._rescue_store import (
    RESCUE_MANIFEST_NAME,
    RESCUE_SCHEMA_VERSION,
)
from sase.workspace_provider._snapshot_capture_payload_objects import (
    account_pack_objects,
    base_commit_objects,
    object_shas,
    validate_index_objects,
    verify_pack,
    write_pack,
)
from sase.workspace_provider._snapshot_capture_payload_trees import (
    build_index_tree,
    collect_worktree_entries,
    write_tree,
)
from sase.workspace_provider._snapshot_git import snapshot_env
from sase.workspace_provider._snapshot_model import (
    DIR_OPERATION_MARKERS,
    FILE_OPERATION_MARKERS,
    SNAPSHOT_INDEX_STAGE_NAME,
    SNAPSHOT_KIND,
    SNAPSHOT_PACK_NAME,
    PreservationError,
    SnapshotRecord,
    SourceState,
)


def capture_into(
    repo_root: Path,
    *,
    state: SourceState,
    rescue_dir: Path,
    snapshot_id: str,
    stamp: str,
    workspace_dir: Path,
    workspace_num: int,
    safe_label: str,
    reason: str,
) -> SnapshotRecord:
    object_dir = rescue_dir / "objects"
    object_dir.mkdir(parents=True, exist_ok=True)
    (object_dir / "info").mkdir(exist_ok=True)
    (object_dir / "pack").mkdir(exist_ok=True)
    env = snapshot_env(object_dir=object_dir, alternate_dirs=(state.object_dir,))
    worktree_entries = collect_worktree_entries(repo_root, state, env=env)
    worktree_tree = write_tree(
        repo_root,
        worktree_entries,
        object_dir=object_dir,
        alternate_dirs=(state.object_dir,),
        tmp_index=rescue_dir / ".tmp-worktree-index",
    )
    index_tree = build_index_tree(
        repo_root,
        state,
        object_dir=object_dir,
        tmp_index=rescue_dir / ".tmp-index",
    )
    unmerged = any(entry.stage != 0 for entry in state.entries)
    index_stage_path = rescue_dir / SNAPSHOT_INDEX_STAGE_NAME
    index_stage_path.write_bytes(state.ls_files_z)
    validate_index_objects(repo_root, state, env=env)
    operation_markers = _copy_operation_markers(state, rescue_dir)
    base, committed_shas = base_commit_objects(repo_root, state=state, env=env)
    shas = object_shas(
        repo_root,
        state=state,
        index_tree=index_tree,
        worktree_tree=worktree_tree,
        committed_shas=committed_shas,
        env=env,
    )
    account_pack_objects(repo_root, shas, env=env)
    pack_path = rescue_dir / SNAPSHOT_PACK_NAME
    write_pack(repo_root, shas, pack_path, env=env)
    verify_pack(pack_path, required_shas=shas)
    _cleanup_capture_temps(rescue_dir, object_dir)
    if not pack_path.is_file() or pack_path.stat().st_size == 0:
        raise PreservationError("snapshot pack is missing after capture")
    if not index_stage_path.is_file():
        raise PreservationError("index-stage payload is missing after capture")
    manifest = {
        "schema_version": RESCUE_SCHEMA_VERSION,
        "kind": SNAPSHOT_KIND,
        "snapshot_id": snapshot_id,
        "timestamp": stamp,
        "repo_root": str(repo_root),
        "workspace_dir": str(workspace_dir),
        "workspace_num": workspace_num,
        "label": safe_label,
        "reason": reason,
        "branch": state.branch,
        "head": state.head,
        "source_fingerprint": asdict(state.fingerprint),
        "base_tree": state.base_tree,
        "base": base,
        "index_tree": index_tree,
        "worktree_tree": worktree_tree,
        "unmerged": unmerged,
        "operation_markers": operation_markers,
        "status_porcelain": state.status_z.decode("utf-8", "surrogateescape").replace(
            "\0", "\n"
        ),
        "files": _payload_names(rescue_dir),
        "payloads": {
            "pack": SNAPSHOT_PACK_NAME,
            "index_stage": SNAPSHOT_INDEX_STAGE_NAME,
        },
        "restore": {
            "objects": (
                "fetch the base commits from the recorded remote when the base mode is "
                f"published; then git unpack-objects < <rescue-dir>/{SNAPSHOT_PACK_NAME}"
            ),
            "head": f"git update-ref HEAD {state.head}",
            "worktree": (
                f"materialize tree {worktree_tree} into the worktree, "
                "then load the captured index"
            ),
            "index": (
                f"git read-tree {index_tree}"
                if index_tree is not None
                else (
                    "git update-index -z --index-info < "
                    f"<rescue-dir>/{SNAPSHOT_INDEX_STAGE_NAME}"
                )
            ),
        },
    }
    manifest_path = publish_manifest(rescue_dir, manifest)
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        manifest_path=manifest_path.resolve(strict=False),
        rescue_dir=rescue_dir.resolve(strict=False),
        head=state.head,
        base_tree=state.base_tree,
        index_tree=index_tree,
        worktree_tree=worktree_tree,
        pack_path=pack_path.resolve(strict=False),
        unmerged=unmerged,
    )


def publish_manifest(rescue_dir: Path, manifest: dict[str, object]) -> Path:
    """Write ``manifest.json`` only after payloads exist. Last step of capture."""
    payload = json.dumps(manifest, indent=2) + "\n"
    target = rescue_dir / RESCUE_MANIFEST_NAME
    tmp = rescue_dir / f".{RESCUE_MANIFEST_NAME}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    for key in ("kind", "snapshot_id", "head", "worktree_tree", "payloads"):
        if key not in loaded:
            raise PreservationError(f"published manifest missing {key}")
    if loaded.get("kind") != SNAPSHOT_KIND:
        raise PreservationError("published manifest is not a verified snapshot")
    return target


def _copy_operation_markers(state: SourceState, rescue_dir: Path) -> list[str]:
    found: list[str] = []
    dest_root = rescue_dir / "operation"
    for name in DIR_OPERATION_MARKERS:
        source = state.git_dir / name
        if source.is_dir():
            shutil.copytree(source, dest_root / name, symlinks=True)
            found.append(name)
    for name in FILE_OPERATION_MARKERS:
        source = state.git_dir / name
        if source.is_file():
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest_root / name)
            found.append(name)
    return sorted(found)


def _cleanup_capture_temps(rescue_dir: Path, object_dir: Path) -> None:
    shutil.rmtree(object_dir, ignore_errors=True)
    for child in rescue_dir.glob(".tmp-*"):
        try:
            child.unlink()
        except OSError:
            pass


def _payload_names(rescue_dir: Path) -> list[str]:
    names: list[str] = []
    for path in sorted(rescue_dir.iterdir()):
        if path.name.startswith(".") or path.name == RESCUE_MANIFEST_NAME:
            continue
        names.append(path.name)
    return names
