"""Workspace cleanup and materialization for linked repositories."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import uuid

from sase._git_remote import git_remotes_match
from sase._linked_repo_config import normalize_path
from sase._linked_repo_paths import (
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
    linked_repo_clone_dir,
    sidecar_repo_clone_dir,
)
from sase.git_lock_retry import run_with_git_lock_retry


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


_DELETE_PATHS_SCRIPT = """
from pathlib import Path
import shutil
import sys

for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass
"""


def _delete_paths_in_background(paths: Sequence[Path]) -> None:
    """Best-effort delete *paths* outside the workspace-prep critical path."""

    if not paths:
        return
    try:
        kwargs: dict[str, Any] = {"start_new_session": True}
        if os.name == "nt":
            kwargs = {
                "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            }
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _DELETE_PATHS_SCRIPT,
                *(str(path) for path in paths),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError:
        for path in paths:
            _remove_path(path)


def clear_workspace_repos(
    workspace_dir: str | Path,
    workspace_num: int,
) -> None:
    """Remove launch-scoped repositories from a numbered host workspace."""

    if workspace_num <= 1:
        return

    workspace = Path(workspace_dir)
    repos_root = workspace.joinpath(*SIDECAR_REPO_CLONES_SUBDIR)
    trash_root = workspace / ".sase" / "trash"
    stale_trash = (
        list(trash_root.iterdir())
        if trash_root.is_dir() and not trash_root.is_symlink()
        else []
    )

    if not os.path.lexists(repos_root):
        _delete_paths_in_background(stale_trash)
        return

    if not repos_root.is_dir() or repos_root.is_symlink():
        _remove_path(repos_root)
        _delete_paths_in_background(stale_trash)
        return

    trash_root.mkdir(parents=True, exist_ok=True)
    trashed_repos = trash_root / f"repos-{uuid.uuid4().hex}"
    os.rename(repos_root, trashed_repos)
    _delete_paths_in_background([*stale_trash, trashed_repos])


def _linked_repo_clone_location(
    workspace_dir: str | Path,
) -> tuple[Path, str, bool] | None:
    """Return ``(host_checkout, name, is_sidecar)`` for a known layout."""

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    layouts = (
        (LINKED_REPO_CLONES_SUBDIR, False),
        (SIDECAR_REPO_CLONES_SUBDIR, True),
    )
    for subdir, is_sidecar in layouts:
        parent_parts = path.parent.parts
        if len(parent_parts) < len(subdir):
            continue
        if tuple(parent_parts[-len(subdir) :]) != subdir:
            continue
        host_checkout = path.parent
        for _ in subdir:
            host_checkout = host_checkout.parent
        return host_checkout, path.name, is_sidecar
    return None


def materialize_linked_repo_workspace(
    *,
    primary_dir: str,
    workspace_dir: str,
    workspace_num: int,
    expected_remote_url: str | None = None,
) -> str:
    """Clone a host-scoped linked workspace and initialize its SDD sidecar."""

    from sase.workspace_provider.utils import ensure_git_clone_at

    location = _linked_repo_clone_location(workspace_dir)
    if location is not None:
        host_checkout, name, is_sidecar = location
        from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

        ensure_git_info_exclude_entry(str(host_checkout), "/sase/repos/")
        if is_sidecar:
            workspace_dir = sidecar_repo_clone_dir(host_checkout, name)
        else:
            workspace_dir = linked_repo_clone_dir(host_checkout, name)

    if expected_remote_url:
        checkout_dir = _materialize_remote_identified_sidecar(
            primary_dir=primary_dir,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            expected_remote_url=expected_remote_url,
        )
    else:
        checkout_dir = ensure_git_clone_at(primary_dir, workspace_num, workspace_dir)
    from sase.workspace_provider.git_exclude import ensure_sase_git_info_excludes

    ensure_sase_git_info_excludes(checkout_dir)
    refreshed = refresh_clean_linked_checkout(checkout_dir)
    if refreshed:
        print(f"[linked-repos] {refreshed}", file=sys.stderr)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return normalize_path(checkout_dir)


def refresh_clean_linked_checkout(checkout_dir: str) -> str | None:
    """Fetch origin and fast-forward a clean checkout that is strictly behind.

    Existing auto-clone workspaces and ``sase repo open`` reuse a valid clone
    without updating HEAD, so a clean ``master``/``main`` can sit behind
    ``origin`` while ``just install`` rebuilds from that stale source. This
    only fast-forwards; dirty, detached, diverged, or fetch/merge failures
    leave the tree unchanged.
    """

    from sase.version._git import (
        classify_git_upstream,
        fetch_git_upstream,
        merge_git_ff_only,
    )

    path = Path(checkout_dir).expanduser()
    try:
        status = classify_git_upstream(path)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    if status.dirty or status.detached or not status.has_upstream:
        return None
    try:
        fetch_git_upstream(status)
        status = classify_git_upstream(path)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    if (
        status.dirty
        or status.detached
        or not status.strictly_behind
        or status.upstream is None
    ):
        return None
    try:
        merge_git_ff_only(path, status.upstream)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    return f"fast-forwarded {path} to {status.upstream}"


def _materialize_remote_identified_sidecar(
    *,
    primary_dir: str,
    workspace_dir: str,
    workspace_num: int,
    expected_remote_url: str,
) -> str:
    """Materialize a sidecar, replacing stale clones of another remote."""

    target = Path(workspace_dir).expanduser()
    if target.is_dir():
        origin = _git_origin_url(target)
        if origin is not None and git_remotes_match(origin, expected_remote_url):
            _set_clone_origin(target, origin, expected_remote_url)
            return str(target)

    if os.path.lexists(target):
        if not (target / ".git").is_dir():
            raise RuntimeError(
                f"Sidecar path at {target} is not a Git clone; refusing to "
                "replace it during remote cutover"
            )
        clean = _git_worktree_is_clean(target)
        if clean is not True:
            detail = "has local changes" if clean is False else "could not be inspected"
            raise RuntimeError(
                f"Sidecar clone at {target} {detail}; refusing to replace "
                "it during remote cutover"
            )

    if workspace_num <= 1:
        from sase.sdd._store_link import ensure_sidecar_sdd_clone

        ensure_sidecar_sdd_clone(target, expected_remote_url, strict=True)
        return str(target)

    if os.path.lexists(target):
        _remove_path(target)

    from sase.sdd._store_link import ensure_sidecar_sdd_clone

    ensure_sidecar_sdd_clone(
        target,
        expected_remote_url,
        reference_repo=Path(primary_dir),
        strict=True,
    )
    return str(target)


def _set_clone_origin(path: Path, current: str, expected: str) -> None:
    if current.strip() == expected.strip():
        return
    try:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", "remote", "set-url", "origin", expected],
                cwd=path,
                capture_output=True,
                text=True,
                check=False,
            ),
            cwd=path,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"could not normalize sidecar origin at {path} to {expected}"
        ) from exc


def _git_origin_url(path: Path) -> str | None:
    # Origin/status inspection is read-only; only set-url above mutates Git.
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_worktree_is_clean(path: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return not result.stdout.strip()
