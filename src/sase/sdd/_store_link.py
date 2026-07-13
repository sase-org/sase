"""Workspace-local clones for separate-repo SDD stores."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from sase.sdd._store_types import (
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    SddStore,
)

_logger = logging.getLogger(__name__)

PrimaryWorkspaceResolver = Callable[[str, int], str]
StoreResolver = Callable[[str | Path, int], SddStore]


def ensure_sidecar_sdd_clone(
    clone_dir: Path,
    remote_url: str,
    *,
    local_source: Path | None = None,
    strict: bool = False,
) -> None:
    """Ensure a split-store sidecar clone exists and tracks its real remote."""

    try:
        clone_dir = clone_dir.expanduser()
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(clone_dir):
            matching = (clone_dir / ".git").is_dir() and _same_git_remote(
                _git_remote_url(clone_dir) or "", remote_url
            )
            if not matching:
                if strict:
                    _replace_workspace_sdd_clone(
                        clone_dir, clone_dir.with_name(".missing-primary"), remote_url
                    )
                    return
                _logger.warning(
                    "Refusing to replace mismatched SDD sidecar clone at %s",
                    clone_dir,
                )
                return
            _set_sdd_origin(clone_dir, remote_url)
            _pull_sdd_clone(clone_dir)
            return

        cloned = False
        if local_source is not None:
            local_source = local_source.expanduser()
            origin = _git_remote_url(local_source)
            if (
                (local_source / ".git").is_dir()
                and origin is not None
                and _same_git_remote(origin, remote_url)
            ):
                cloned = _clone_sdd_store_from_primary(local_source, clone_dir)
                if cloned:
                    _set_sdd_origin(clone_dir, remote_url)
                    _pull_sdd_clone(clone_dir)

        if not cloned:
            cloned = _clone_sdd_store(remote_url, clone_dir)
        if not cloned and strict:
            raise SddMaterializationError(
                f"could not create SDD sidecar clone at {clone_dir}"
            )
    except Exception as exc:
        if strict:
            if isinstance(exc, SddMaterializationError):
                raise
            raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
        _logger.warning(
            "Failed to ensure SDD sidecar clone at %s", clone_dir, exc_info=True
        )


def ensure_workspace_sdd_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    resolve_store: StoreResolver,
    primary_workspace_dir: PrimaryWorkspaceResolver,
    strict: bool = False,
) -> None:
    """Ensure a workspace-local clone of a separate-repo SDD store."""

    workspace = Path(workspace_dir).expanduser()
    try:
        store = resolve_store(workspace, workspace_num)
        if store.storage != SDD_STORAGE_SEPARATE_REPO:
            return

        workspace_sdd = workspace / ".sase" / "sdd"
        primary = Path(primary_workspace_dir(str(workspace), workspace_num))
        primary_sdd = primary / ".sase" / "sdd"

        if _paths_same_file(workspace_sdd, primary_sdd):
            if not _is_matching_store_clone(workspace_sdd, store) and strict:
                raise SddMaterializationError(
                    f"primary SDD sidecar clone is missing or mismatched: {workspace_sdd}"
                )
            return

        workspace_sdd.parent.mkdir(parents=True, exist_ok=True)
        if workspace_sdd.is_symlink():
            if strict:
                _replace_workspace_sdd_clone(
                    workspace_sdd, primary_sdd, store.remote_url
                )
                return
            workspace_sdd.unlink()

        if os.path.lexists(workspace_sdd):
            if not workspace_sdd.is_dir():
                if strict:
                    _replace_workspace_sdd_clone(
                        workspace_sdd, primary_sdd, store.remote_url
                    )
                    return
                _logger.warning("Refusing to overwrite SDD path at %s", workspace_sdd)
                return
            if not (workspace_sdd / ".git").is_dir():
                if strict:
                    _replace_workspace_sdd_clone(
                        workspace_sdd, primary_sdd, store.remote_url
                    )
                    return
                _logger.warning(
                    "Refusing to overwrite non-git SDD directory at %s",
                    workspace_sdd,
                )
                return
            if not _is_matching_store_clone(workspace_sdd, store):
                if strict:
                    _replace_workspace_sdd_clone(
                        workspace_sdd, primary_sdd, store.remote_url
                    )
                    return
                _logger.warning(
                    "Refusing to sync SDD clone at %s because its origin does not "
                    "match the configured SDD store remote",
                    workspace_sdd,
                )
                return
            _sync_workspace_sdd_clone(workspace_sdd, primary_sdd, store.remote_url)
            return

        cloned = _clone_sdd_store_from_primary(primary_sdd, workspace_sdd)
        if cloned and store.remote_url:
            _set_sdd_origin(workspace_sdd, store.remote_url)
        if not cloned and store.remote_url:
            cloned = _clone_sdd_store(store.remote_url, workspace_sdd)
        if cloned:
            _sync_workspace_sdd_clone(workspace_sdd, primary_sdd, store.remote_url)
        elif strict:
            raise SddMaterializationError(
                f"could not create workspace SDD sidecar clone at {workspace_sdd}"
            )
    except Exception as exc:
        if strict:
            if isinstance(exc, SddMaterializationError):
                raise
            raise SddMaterializationError(str(exc) or type(exc).__name__) from exc
        _logger.warning(
            "Failed to ensure workspace SDD clone for workspace %s",
            workspace,
            exc_info=True,
        )


def _replace_workspace_sdd_clone(
    workspace_sdd: Path,
    primary_sdd: Path,
    remote_url: str | None,
) -> None:
    """Atomically replace legacy workspace content after primary adoption."""

    temp = workspace_sdd.with_name(f".sdd.clone-{uuid.uuid4().hex}")
    backup = workspace_sdd.with_name(f".sdd.recovery-{uuid.uuid4().hex}")
    cloned = _clone_sdd_store_from_primary(primary_sdd, temp)
    if cloned and remote_url:
        _set_sdd_origin(temp, remote_url)
    if not cloned and remote_url:
        cloned = _clone_sdd_store(remote_url, temp)
    if not cloned:
        shutil.rmtree(temp, ignore_errors=True)
        raise SddMaterializationError(
            f"could not replace legacy workspace SDD path at {workspace_sdd}"
        )

    had_existing = os.path.lexists(workspace_sdd)
    if had_existing:
        workspace_sdd.replace(backup)
    try:
        temp.replace(workspace_sdd)
    except Exception:
        if (
            had_existing
            and os.path.lexists(backup)
            and not os.path.lexists(workspace_sdd)
        ):
            backup.replace(workspace_sdd)
        raise
    if had_existing:
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup, ignore_errors=True)
        else:
            try:
                backup.unlink()
            except OSError:
                pass


def _sync_workspace_sdd_clone(
    workspace_sdd: Path,
    primary_sdd: Path,
    remote_url: str | None,
) -> None:
    """Refresh an existing workspace SDD clone without failing launch."""

    if remote_url is not None:
        _set_sdd_origin(workspace_sdd, remote_url)

    if _pull_sdd_clone(workspace_sdd):
        return

    if not _paths_same_file(workspace_sdd, primary_sdd):
        _fast_forward_workspace_clone_from_primary(workspace_sdd, primary_sdd)


def _pull_sdd_clone(workspace_sdd: Path) -> bool:
    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        result = run_sdd_git(
            ["pull", "--rebase"],
            cwd=workspace_sdd,
            op="sdd.clone.pull",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning("Timed out pulling workspace SDD clone %s", workspace_sdd)
        return False
    except Exception:
        _logger.warning(
            "Failed to pull workspace SDD clone %s",
            workspace_sdd,
            exc_info=True,
        )
        return False
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout or "").strip()
    _logger.warning(
        "Failed to pull workspace SDD clone %s: %s",
        workspace_sdd,
        detail or f"git pull exited {result.returncode}",
    )
    return False


def _clone_sdd_store(remote_url: str, workspace_sdd: Path) -> bool:
    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        result = run_sdd_git(
            ["clone", remote_url, str(workspace_sdd)],
            cwd=workspace_sdd.parent,
            op="sdd.clone.remote",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning("Timed out cloning SDD store %s", remote_url)
        return False
    except Exception:
        _logger.warning(
            "Failed to clone SDD store %s into %s",
            remote_url,
            workspace_sdd,
            exc_info=True,
        )
        return False
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout or "").strip()
    _logger.warning(
        "Failed to clone SDD store %s into %s: %s",
        remote_url,
        workspace_sdd,
        detail or f"git clone exited {result.returncode}",
    )
    return False


def _clone_sdd_store_from_primary(primary_sdd: Path, workspace_sdd: Path) -> bool:
    if not (primary_sdd / ".git").is_dir():
        return False
    if _paths_same_file(primary_sdd, workspace_sdd):
        return workspace_sdd.is_dir()

    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        result = run_sdd_git(
            ["clone", str(primary_sdd), str(workspace_sdd)],
            cwd=workspace_sdd.parent,
            op="sdd.clone.primary",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning(
            "Timed out cloning workspace SDD store %s from primary %s",
            workspace_sdd,
            primary_sdd,
        )
        return False
    except Exception:
        _logger.warning(
            "Failed to clone workspace SDD store %s from primary %s",
            workspace_sdd,
            primary_sdd,
            exc_info=True,
        )
        return False
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout or "").strip()
    _logger.warning(
        "Failed to clone workspace SDD store %s from primary %s: %s",
        workspace_sdd,
        primary_sdd,
        detail or f"git clone exited {result.returncode}",
    )
    return False


def _set_sdd_origin(workspace_sdd: Path, remote_url: str) -> None:
    current = _git_remote_url(workspace_sdd)
    if current is not None and _same_git_remote(current, remote_url):
        return

    from sase.sdd._commit import SddGitCommandTimeout, run_sdd_git

    command = (
        ["remote", "set-url", "origin", remote_url]
        if current
        else ["remote", "add", "origin", remote_url]
    )
    try:
        result = run_sdd_git(
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


def _is_matching_store_clone(path: Path, store: SddStore) -> bool:
    """Return true when *path* looks like a clone of the SDD sidecar repo.

    A missing ``.git`` marks unrelated content. When the store's remote URL is
    known, the clone's ``origin`` must match it; an unknown store remote skips the
    check so a legitimately lagging clone is still recognized as a store clone.
    """

    if not (path / ".git").is_dir():
        return False
    if store.remote_url is None:
        return True
    origin = _git_remote_url(path)
    if origin is None:
        return False
    return _same_git_remote(origin, store.remote_url)


is_matching_store_clone = _is_matching_store_clone


def _fast_forward_workspace_clone_from_primary(
    workspace_sdd: Path, primary_sdd: Path
) -> None:
    """Best-effort fast-forward a workspace store clone from the primary store.

    Pulling from the on-disk primary store is race-free and needs no network.
    Never raises into the launch path.
    """

    if not (primary_sdd / ".git").is_dir():
        return
    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        result = run_sdd_git(
            ["pull", "--ff-only", str(primary_sdd)],
            cwd=workspace_sdd,
            op="sdd.clone.fast_forward",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning(
            "Timed out fast-forwarding workspace SDD clone %s from %s",
            workspace_sdd,
            primary_sdd,
        )
        return
    except Exception:
        _logger.warning(
            "Failed to fast-forward workspace SDD clone %s from %s",
            workspace_sdd,
            primary_sdd,
            exc_info=True,
        )
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _logger.warning(
            "Failed to fast-forward workspace SDD clone %s from %s: %s",
            workspace_sdd,
            primary_sdd,
            detail or f"git pull exited {result.returncode}",
        )


def _git_remote_url(path: Path) -> str | None:
    result = _run_local_git(
        ["remote", "get-url", "origin"], cwd=path, op="sdd.clone.remote"
    )
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _same_git_remote(left: str, right: str) -> bool:
    return _normalize_git_remote(left) == _normalize_git_remote(right)


def _normalize_git_remote(url: str) -> str:
    trimmed = url.strip().rstrip("/")
    if trimmed.endswith(".git"):
        trimmed = trimmed[: -len(".git")]
    return trimmed


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


def _paths_same_file(left: Path, right: Path) -> bool:
    if left.expanduser().absolute() == right.expanduser().absolute():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False
