"""Low-level Git metadata helpers for provider-owned SDD stores."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess

from sase._git_remote import git_remotes_match
from sase.sdd._store_types import SddStore

_logger = logging.getLogger(__name__)


def set_sdd_origin(workspace_sdd: Path, remote_url: str) -> None:
    current = git_remote_url(workspace_sdd)
    if current is not None and current.strip() == remote_url.strip():
        return

    from sase.sdd._commit import SddGitCommandTimeout
    from sase.sdd._git_contention import run_sdd_git_write

    command = (
        ["remote", "set-url", "origin", remote_url]
        if current
        else ["remote", "add", "origin", remote_url]
    )
    try:
        result = run_sdd_git_write(
            command,
            cwd=workspace_sdd,
            op="sdd.clone.origin",
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning("Timed out setting SDD origin in %s", workspace_sdd)
        return
    except Exception:
        _logger.warning(
            "Failed to set SDD origin in %s",
            workspace_sdd,
            exc_info=True,
        )
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _logger.warning(
            "Failed to set SDD origin in %s: %s",
            workspace_sdd,
            detail or f"git remote exited {result.returncode}",
        )


def is_matching_store_clone(path: Path, store: SddStore) -> bool:
    """Return true when *path* looks like a clone of the SDD sidecar repo.

    A missing ``.git`` marks unrelated content. When the store's remote URL is
    known, the clone's ``origin`` must match it; an unknown store remote skips the
    check so a legitimately lagging clone is still recognized as a store clone.
    """

    if not (path / ".git").is_dir():
        return False
    if store.remote_url is None:
        return True
    origin = git_remote_url(path)
    if origin is None:
        return False
    return same_git_remote(origin, store.remote_url)


def git_remote_url(path: Path) -> str | None:
    result = _run_local_git(
        ["remote", "get-url", "origin"], cwd=path, op="sdd.clone.remote"
    )
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def same_git_remote(left: str, right: str) -> bool:
    return git_remotes_match(left, right)


def _run_local_git(
    args: list[str], *, cwd: Path, op: str
) -> subprocess.CompletedProcess[str] | None:
    from sase.sdd._commit import SddGitCommandTimeout, run_sdd_git

    try:
        return run_sdd_git(
            args,
            cwd=cwd,
            op=op,
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        return None
    except Exception:
        _logger.warning(
            "Local git command failed in %s: git %s",
            cwd,
            " ".join(args),
            exc_info=True,
        )
        return None


def paths_same_file(left: Path, right: Path) -> bool:
    if left.expanduser().absolute() == right.expanduser().absolute():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False
