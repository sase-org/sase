"""Source-state reading and snapshot orchestration."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sase.workspace_provider._rescue_store import (
    RescueRecord,
    new_rescue_dir,
    notify_rescue,
    reap_rescue_store,
    sanitize_label,
)
from sase.workspace_provider._snapshot_capture_common import is_managed_sidecar_rel
from sase.workspace_provider._snapshot_capture_payload import capture_into
from sase.workspace_provider._snapshot_git import (
    digest_bytes,
    file_mode_for_path,
    git_output,
    nested_git_root,
    parse_ls_files_stage,
    require_git,
    run_git_bytes,
    safe_repo_path,
    special_index_paths,
    status_paths,
)
from sase.workspace_provider._snapshot_model import (
    PreservationError,
    SnapshotRecord,
    SourceFingerprint,
    SourceState,
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
    if not _has_work(repo_root, state):
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
    record = capture_into(
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
        if is_managed_sidecar_rel(rel):
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


def _has_work(repo_root: Path, state: SourceState) -> bool:
    for rel in status_paths(state.status_z):
        if not is_managed_sidecar_rel(rel):
            return True
    # Sidecar-only status means the main checkout has no work of its own;
    # sidecars are rescued through their own boundaries.
    return any(entry.stage != 0 for entry in state.entries) or any(
        not is_managed_sidecar_rel(path) for path in special_index_paths(repo_root)
    )


def _refuse_nested_repositories(repo_root: Path, state: SourceState) -> None:
    seen: set[Path] = set()
    for rel in status_paths(state.status_z):
        if is_managed_sidecar_rel(rel):
            continue
        nested = nested_git_root(repo_root, rel)
        if nested is not None:
            if is_managed_sidecar_rel(nested.relative_to(repo_root).as_posix()):
                continue
            seen.add(nested)
    for entry in state.entries:
        if entry.mode == "160000":
            if is_managed_sidecar_rel(entry.path):
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


def _discard_incomplete(allocated: list[Path]) -> None:
    for path in allocated:
        shutil.rmtree(path, ignore_errors=True)
    allocated.clear()
