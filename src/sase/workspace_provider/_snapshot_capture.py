"""Non-destructive verified snapshot capture."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sase.workspace_provider._rescue_store import (
    RESCUE_MANIFEST_NAME,
    RESCUE_SCHEMA_VERSION,
    RescueRecord,
    new_rescue_dir,
    notify_rescue,
    reap_rescue_store,
    sanitize_label,
)
from sase.workspace_provider._snapshot_git import (
    digest_bytes,
    file_mode_for_path,
    git_output,
    nested_git_root,
    parse_ls_files_stage,
    read_worktree_bytes,
    require_git,
    run_git_bytes,
    safe_repo_path,
    snapshot_env,
    status_paths,
)
from sase.workspace_provider._snapshot_model import (
    SNAPSHOT_INDEX_STAGE_NAME,
    SNAPSHOT_KIND,
    SNAPSHOT_MAX_BYTES,
    SNAPSHOT_PACK_NAME,
    IndexEntry,
    PreservationError,
    SnapshotRecord,
    SourceFingerprint,
    SourceState,
    _DIR_OPERATION_MARKERS,
    _FILE_OPERATION_MARKERS,
)


def snapshot_git_repo(
    repo_root: str | Path,
    *,
    workspace_dir: str | Path,
    workspace_num: int,
    label: str,
    reason: str,
) -> SnapshotRecord | None:
    """Capture a verified snapshot of *repo_root* without mutating it.

    Returns ``None`` only when the checkout is a proven no-work tree. Any
    incomplete preservation raises :class:`PreservationError` rather than
    returning ``None``.
    """
    allocated: list[Path] = []
    try:
        return _snapshot_git_repo(
            Path(repo_root),
            workspace_dir=Path(workspace_dir),
            workspace_num=workspace_num,
            label=label,
            reason=reason,
            allocated=allocated,
        )
    except PreservationError:
        _discard_incomplete(allocated)
        raise
    except Exception as exc:
        _discard_incomplete(allocated)
        raise PreservationError(f"checkout snapshot failed: {exc}") from exc


def snapshot_source_fingerprint(repo_root: str | Path) -> dict[str, str]:
    """Return a stable read-only fingerprint for deciding whether to reuse a snapshot."""
    repo = Path(repo_root)
    before = read_source_state(repo).fingerprint
    after = read_source_state(repo).fingerprint
    if before != after:
        raise PreservationError(
            "source checkout changed while checking its fingerprint"
        )
    return asdict(after)


def _snapshot_git_repo(
    repo_root: Path,
    *,
    workspace_dir: Path,
    workspace_num: int,
    label: str,
    reason: str,
    allocated: list[Path],
) -> SnapshotRecord | None:
    state = read_source_state(repo_root)
    if not _has_work(state):
        return None
    _refuse_nested_repositories(repo_root, state)
    safe_label = sanitize_label(label or repo_root.name)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    unique = f"{time.time_ns():x}"
    digest = hashlib.sha1(
        f"{repo_root}|{state.head}|{stamp}|{unique}".encode()
    ).hexdigest()[:12]
    snapshot_id = f"{stamp}-{digest}"
    rescue_dir = new_rescue_dir(
        workspace_dir,
        f"{stamp}-ws{workspace_num}-{safe_label}-{digest}",
    )
    rescue_dir.mkdir(parents=True, exist_ok=True)
    allocated.append(rescue_dir)
    record = _capture_into(
        repo_root,
        state=state,
        rescue_dir=rescue_dir,
        snapshot_id=snapshot_id,
        stamp=stamp,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        safe_label=safe_label,
        reason=reason,
    )
    after = read_source_state(repo_root)
    if after.fingerprint != state.fingerprint:
        raise PreservationError("source checkout changed during snapshot capture")
    notify_rescue(
        RescueRecord(
            rescue_dir=record.rescue_dir,
            manifest_path=record.manifest_path,
            note="verified checkout snapshot (base, index, worktree)",
        ),
        label=safe_label,
        reason=reason,
    )
    reap_rescue_store()
    allocated.clear()
    return record


def read_source_state(repo_root: Path) -> SourceState:
    """Read HEAD, index, and diffs; fail closed on git errors."""
    git_dir_raw = git_output(repo_root, "rev-parse", "--absolute-git-dir")
    if not git_dir_raw:
        raise PreservationError(f"not a git repository: {repo_root}")
    git_dir = Path(git_dir_raw)
    head = git_output(repo_root, "rev-parse", "--verify", "HEAD")
    if not head:
        raise PreservationError(f"could not resolve HEAD in {repo_root}")
    base_tree = git_output(repo_root, "rev-parse", "--verify", "HEAD^{tree}")
    branch_result = run_git_bytes(repo_root, "symbolic-ref", "-q", "--short", "HEAD")
    branch = (
        branch_result.stdout.decode("utf-8", "surrogateescape").strip() or None
        if branch_result.returncode == 0
        else None
    )
    status = require_git(
        run_git_bytes(repo_root, "status", "--porcelain=v1", "-z", "-uall"),
        "git status",
    )
    ls_files = require_git(
        run_git_bytes(repo_root, "ls-files", "-z", "--stage"),
        "git ls-files --stage",
    )
    diff_cached = require_git(
        run_git_bytes(repo_root, "diff", "--binary", "--cached", "HEAD"),
        "git diff --cached",
    )
    diff_worktree = require_git(
        run_git_bytes(repo_root, "diff", "--binary", "HEAD"),
        "git diff",
    )
    untracked = require_git(
        run_git_bytes(repo_root, "ls-files", "-z", "-o", "--exclude-standard"),
        "git ls-files --others",
    )
    object_dir = _absolute_git_path(repo_root, "objects")
    index_path = _absolute_git_path(repo_root, "index")
    index_bytes = (
        index_path.read_bytes()
        if index_path.is_file() or os.path.lexists(index_path)
        else b""
    )
    fingerprint = SourceFingerprint(
        head=head,
        index_digest=digest_bytes(index_bytes),
        status_digest=digest_bytes(status),
        ls_files_digest=digest_bytes(ls_files),
        diff_cached_digest=digest_bytes(diff_cached),
        diff_worktree_digest=digest_bytes(diff_worktree),
        untracked_digest=_digest_untracked(repo_root, untracked),
    )
    return SourceState(
        fingerprint=fingerprint,
        head=head,
        base_tree=base_tree,
        branch=branch,
        status_z=status,
        ls_files_z=ls_files,
        entries=parse_ls_files_stage(ls_files),
        git_dir=git_dir,
        object_dir=object_dir,
        index_path=index_path,
    )


def _digest_untracked(repo_root: Path, paths_z: bytes) -> str:
    """Hash untracked path metadata and bytes, which Git diffs do not include."""
    digest = hashlib.sha256()
    for raw_path in paths_z.split(b"\0"):
        if not raw_path:
            continue
        rel = os.fsdecode(raw_path)
        # Sidecar clones have their own snapshot/rescue boundary. Including
        # them here would hash nested git directories as blobs and couple the
        # parent fingerprint to trees this snapshot must not capture.
        if _is_managed_sidecar_rel(rel):
            continue
        path = safe_repo_path(repo_root, rel)
        digest.update(len(raw_path).to_bytes(8, "big"))
        digest.update(raw_path)
        if not os.path.lexists(path):
            digest.update(b"missing\0")
            continue
        if path.is_dir() and not path.is_symlink():
            digest.update(b"dir\0")
            continue
        digest.update(file_mode_for_path(path).encode("ascii") + b"\0")
        content_digest = hashlib.sha256()
        size = 0
        if path.is_symlink():
            target = os.fsencode(os.readlink(path))
            content_digest.update(target)
            size = len(target)
        else:
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    content_digest.update(chunk)
                    size += len(chunk)
        digest.update(size.to_bytes(8, "big"))
        digest.update(content_digest.digest())
    return digest.hexdigest()


def _has_work(state: SourceState) -> bool:
    from sase.workspace_provider._snapshot_git import status_paths as _status_paths

    for rel in _status_paths(state.status_z):
        if not _is_managed_sidecar_rel(rel):
            return True
    # Sidecar-only status means the main checkout has no work of its own;
    # sidecars are rescued through their own boundaries.
    return any(entry.stage != 0 for entry in state.entries)


def _is_managed_sidecar_rel(rel: str) -> bool:
    """Whether *rel* lives under the managed sidecar root.

    Clones under ``sase/repos/`` have their own rescue boundaries
    (sidecar/linked/external rescue before eviction), so the main-checkout
    snapshot neither captures nor refuses them.
    """
    return rel == "sase/repos" or rel.startswith("sase/repos/")


def _refuse_nested_repositories(repo_root: Path, state: SourceState) -> None:
    seen: set[Path] = set()
    for rel in status_paths(state.status_z):
        if _is_managed_sidecar_rel(rel):
            continue
        nested = nested_git_root(repo_root, rel)
        if nested is not None:
            if _is_managed_sidecar_rel(nested.relative_to(repo_root).as_posix()):
                continue
            seen.add(nested)
    for entry in state.entries:
        if entry.mode == "160000":
            if _is_managed_sidecar_rel(entry.path):
                continue
            path = safe_repo_path(repo_root, entry.path)
            if path.is_dir():
                dirty = run_git_bytes(path, "status", "--porcelain=v1", "-z", "-uall")
                if dirty.returncode == 0 and any(
                    part for part in dirty.stdout.split(b"\0") if part
                ):
                    seen.add(path)
    if seen:
        names = ", ".join(sorted(str(path) for path in seen))
        raise PreservationError(
            f"refusing to snapshot nested repository content: {names}"
        )


def _capture_into(
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
    byte_total = 0
    worktree_entries, byte_total = _worktree_entries(
        repo_root, state, env=env, byte_total=byte_total
    )
    worktree_tree = _write_tree(
        repo_root,
        worktree_entries,
        object_dir=object_dir,
        alternate_dirs=(state.object_dir,),
        tmp_index=rescue_dir / ".tmp-worktree-index",
    )
    index_tree = _index_tree(
        repo_root,
        state,
        object_dir=object_dir,
        tmp_index=rescue_dir / ".tmp-index",
    )
    unmerged = any(entry.stage != 0 for entry in state.entries)
    index_stage_path = rescue_dir / SNAPSHOT_INDEX_STAGE_NAME
    index_stage_path.write_bytes(state.ls_files_z)
    _copy_index_blobs(repo_root, state, env=env, byte_total=byte_total)
    operation_markers = _copy_operation_markers(state, rescue_dir)
    shas = _object_shas(
        repo_root,
        state=state,
        index_tree=index_tree,
        worktree_tree=worktree_tree,
        env=env,
    )
    pack_path = rescue_dir / SNAPSHOT_PACK_NAME
    _write_pack(repo_root, shas, pack_path, env=env)
    _verify_pack(
        pack_path,
        required_shas=[
            state.head,
            state.base_tree,
            worktree_tree,
            *([index_tree] if index_tree is not None else []),
        ],
    )
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
            "objects": f"git unpack-objects < <rescue-dir>/{SNAPSHOT_PACK_NAME}",
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


def _worktree_entries(
    repo_root: Path,
    state: SourceState,
    *,
    env: dict[str, str],
    byte_total: int,
) -> tuple[list[IndexEntry], int]:
    # Live worktree bytes can belong to any index stage. Delete/modify
    # conflicts are stages 1+3; add/delete can be stage 3 only.
    tracked = {entry.path for entry in state.entries}
    untracked = require_git(
        run_git_bytes(repo_root, "ls-files", "-z", "-o", "--exclude-standard"),
        "git ls-files --others",
    )
    paths = set(tracked)
    for item in untracked.split(b"\0"):
        if item:
            paths.add(os.fsdecode(item))
    entries: list[IndexEntry] = []
    for rel in sorted(paths):
        if _is_managed_sidecar_rel(rel):
            continue
        path = safe_repo_path(repo_root, rel)
        if not path.exists() and not os.path.lexists(path):
            continue
        if path.is_dir() and not path.is_symlink():
            nested = nested_git_root(repo_root, rel)
            if nested is not None:
                if _is_managed_sidecar_rel(nested.relative_to(repo_root).as_posix()):
                    continue
                raise PreservationError(
                    f"refusing to snapshot nested repository content: {nested}"
                )
            continue
        data = read_worktree_bytes(path)
        byte_total = _account_bytes(byte_total, len(data), rel)
        sha = _hash_blob(repo_root, data, env=env)
        entries.append(
            IndexEntry(
                mode=file_mode_for_path(path),
                sha=sha,
                stage=0,
                path=rel,
            )
        )
    return entries, byte_total


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


def _write_tree(
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


def _index_tree(
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


def _copy_index_blobs(
    repo_root: Path,
    state: SourceState,
    *,
    env: dict[str, str],
    byte_total: int,
) -> None:
    seen: set[str] = set()
    for entry in state.entries:
        if entry.sha in seen or entry.mode == "160000":
            continue
        seen.add(entry.sha)
        blob = require_git(
            run_git_bytes(repo_root, "cat-file", "blob", entry.sha),
            f"git cat-file blob {entry.sha}",
        )
        byte_total = _account_bytes(byte_total, len(blob), entry.path)
        hashed = _hash_blob(repo_root, blob, env=env)
        if hashed != entry.sha:
            raise PreservationError(
                f"index blob {entry.sha} hashed as {hashed} for {entry.path}"
            )


def _object_shas(
    repo_root: Path,
    *,
    state: SourceState,
    index_tree: str | None,
    worktree_tree: str,
    env: dict[str, str],
) -> set[str]:
    shas: set[str] = {state.head, state.base_tree, worktree_tree}
    shas.update(_rev_list_objects(repo_root, state.head, env=env))
    shas.update(_tree_objects(repo_root, worktree_tree, env=env))
    if index_tree is not None:
        shas.add(index_tree)
        shas.update(_tree_objects(repo_root, index_tree, env=env))
    for entry in state.entries:
        shas.add(entry.sha)
    return {sha for sha in shas if sha}


def _rev_list_objects(repo_root: Path, rev: str, *, env: dict[str, str]) -> set[str]:
    output = require_git(
        run_git_bytes(repo_root, "rev-list", "--objects", "--no-walk", rev, env=env),
        f"git rev-list --objects {rev}",
    )
    return _shas_from_object_list(output)


def _tree_objects(repo_root: Path, tree: str, *, env: dict[str, str]) -> set[str]:
    shas = {tree}
    output = require_git(
        run_git_bytes(
            repo_root, "ls-tree", "-r", "-t", "-z", "--full-tree", tree, env=env
        ),
        f"git ls-tree {tree}",
    )
    for item in output.split(b"\0"):
        if not item:
            continue
        meta = item.split(b"\t", 1)[0]
        parts = meta.split(b" ")
        if len(parts) >= 3:
            shas.add(parts[2].decode("ascii"))
    return shas


def _shas_from_object_list(output: bytes) -> set[str]:
    shas: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        sha = line.split(b" ", 1)[0].decode("ascii")
        if sha:
            shas.add(sha)
    return shas


def _write_pack(
    repo_root: Path,
    shas: set[str],
    pack_path: Path,
    *,
    env: dict[str, str],
) -> None:
    payload = ("\n".join(sorted(shas)) + "\n").encode("ascii")
    result = run_git_bytes(
        repo_root,
        "pack-objects",
        "--stdout",
        "--delta-base-offset",
        env=env,
        input_bytes=payload,
    )
    packed = require_git(result, "git pack-objects")
    if not packed:
        raise PreservationError("git pack-objects wrote an empty pack")
    _account_bytes(0, len(packed), SNAPSHOT_PACK_NAME)
    pack_path.write_bytes(packed)


def _verify_pack(pack_path: Path, *, required_shas: list[str]) -> None:
    """Prove the pack is self-contained without touching the source checkout.

    ``git index-pack`` outside a repository aborts (SIGSEGV on this host), so
    verification unpacks into a throwaway git dir and checks required objects.
    """
    verify_dir = pack_path.parent / ".verify-git"
    try:
        verify_dir.mkdir()
        require_git(
            run_git_bytes(verify_dir, "init", "--bare"),
            "git init --bare",
        )
        require_git(
            run_git_bytes(
                verify_dir,
                "unpack-objects",
                "-q",
                input_bytes=pack_path.read_bytes(),
            ),
            "git unpack-objects",
        )
        for sha in required_shas:
            kind = (
                require_git(
                    run_git_bytes(verify_dir, "cat-file", "-t", sha),
                    f"git cat-file -t {sha}",
                )
                .strip()
                .decode("ascii")
            )
            if kind not in {"commit", "tree", "blob"}:
                raise PreservationError(
                    f"snapshot pack object {sha} has unexpected type {kind}"
                )
    finally:
        shutil.rmtree(verify_dir, ignore_errors=True)


def _copy_operation_markers(state: SourceState, rescue_dir: Path) -> list[str]:
    found: list[str] = []
    dest_root = rescue_dir / "operation"
    for name in _DIR_OPERATION_MARKERS:
        source = state.git_dir / name
        if source.is_dir():
            shutil.copytree(source, dest_root / name, symlinks=True)
            found.append(name)
    for name in _FILE_OPERATION_MARKERS:
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


def _absolute_git_path(repo_root: Path, git_path: str) -> Path:
    result = run_git_bytes(
        repo_root, "rev-parse", "--path-format=absolute", "--git-path", git_path
    )
    if result.returncode == 0:
        raw = result.stdout.decode("utf-8", "surrogateescape").strip()
        if raw:
            return Path(raw)
    rel = git_output(repo_root, "rev-parse", "--git-path", git_path)
    path = Path(rel)
    if not path.is_absolute():
        path = repo_root / path
    return path


def _account_bytes(total: int, added: int, label: str) -> int:
    new_total = total + added
    if added > SNAPSHOT_MAX_BYTES or new_total > SNAPSHOT_MAX_BYTES:
        raise PreservationError(
            f"snapshot payload {label} is {added} bytes; "
            f"total {new_total} exceeds the {SNAPSHOT_MAX_BYTES}-byte cap"
        )
    return new_total


def _discard_incomplete(allocated: list[Path]) -> None:
    for path in allocated:
        shutil.rmtree(path, ignore_errors=True)
    allocated.clear()
