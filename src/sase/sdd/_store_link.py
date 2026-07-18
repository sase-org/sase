"""Workspace-local clones for separate-repo SDD stores."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from pathlib import Path
import shutil
import uuid

from sase._git_remote import is_http_git_remote
from sase.sdd._store_git import (
    git_remote_url as _git_remote_url,
    is_matching_store_clone as _is_matching_store_clone,
    paths_same_file as _paths_same_file,
    same_git_remote as _same_git_remote,
    set_sdd_origin as _set_sdd_origin,
)
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
    strict: bool = False,
    fresh: bool = False,
) -> None:
    """Ensure a split-store sidecar clone exists and tracks its real remote.

    ``fresh`` forces a remote integration even within the configured TTL.
    """

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
            if (
                strict
                and (_git_remote_url(clone_dir) or "").strip() != remote_url.strip()
            ):
                raise SddMaterializationError(
                    f"could not normalize SDD sidecar origin at {clone_dir}"
                )
            _pull_sdd_clone(clone_dir, strict=strict, fresh=fresh)
            return

        cloned = _clone_sdd_store(remote_url, clone_dir, strict=strict)
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
    finally:
        from sase.workspace_provider.git_exclude import ensure_sase_git_info_excludes

        ensure_sase_git_info_excludes(str(clone_dir))


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
            _sync_workspace_sdd_clone(
                workspace_sdd,
                primary_sdd,
                store.remote_url,
                strict=strict,
            )
            return

        cloned = _clone_sdd_store_from_primary(primary_sdd, workspace_sdd)
        if cloned and store.remote_url:
            _set_sdd_origin(workspace_sdd, store.remote_url)
        if not cloned and store.remote_url:
            cloned = _clone_sdd_store(store.remote_url, workspace_sdd)
        if cloned:
            _sync_workspace_sdd_clone(
                workspace_sdd,
                primary_sdd,
                store.remote_url,
                strict=strict,
            )
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
    finally:
        from sase.workspace_provider.git_exclude import ensure_sase_git_info_excludes

        ensure_sase_git_info_excludes(str(workspace / ".sase" / "sdd"))


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
    *,
    strict: bool,
) -> None:
    """Refresh an existing workspace SDD clone without failing launch."""

    if remote_url is not None:
        _set_sdd_origin(workspace_sdd, remote_url)

    if _pull_sdd_clone(workspace_sdd, strict=strict):
        return

    if not _paths_same_file(workspace_sdd, primary_sdd):
        _fast_forward_workspace_clone_from_primary(workspace_sdd, primary_sdd)


def _pull_sdd_clone(
    workspace_sdd: Path,
    *,
    strict: bool = False,
    fresh: bool = False,
) -> bool:
    from sase.sdd._integration_marker import (
        bead_refresh_mode,
        integration_is_fresh,
    )

    if (
        not fresh
        and bead_refresh_mode() != "blocking"
        and integration_is_fresh(workspace_sdd)
    ):
        return True

    from sase.sdd._repository_transaction import (
        SddIntegrationStatus,
        integrate_sdd_repository,
    )

    outcome = integrate_sdd_repository(
        workspace_sdd,
        beads_dir=(workspace_sdd / "beads"),
        op_prefix="sdd.clone",
    )
    if outcome.succeeded:
        return True
    detail = outcome.error or f"SDD integration ended with {outcome.status.value}"
    if outcome.status is SddIntegrationStatus.UNRECOVERABLE:
        from sase.sdd._repository_transaction import SddRepositoryHealthError

        raise SddRepositoryHealthError(detail)
    if strict and outcome.status not in {
        SddIntegrationStatus.REMOTE_UNAVAILABLE,
    }:
        raise SddMaterializationError(detail)
    _logger.warning(
        "Failed to pull workspace SDD clone %s: %s",
        workspace_sdd,
        detail,
    )
    return False


def _clone_sdd_store(
    remote_url: str,
    workspace_sdd: Path,
    *,
    strict: bool = False,
) -> bool:
    if is_http_git_remote(remote_url):
        return _handle_failed_sdd_clone(
            workspace_sdd,
            f"refusing HTTP(S) SDD sidecar remote {remote_url!r}; "
            "materialization requires an SSH or local Git remote and Git was "
            "not invoked",
            strict=strict,
        )

    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        clone_env = os.environ.copy()
        clone_env["GIT_TERMINAL_PROMPT"] = "0"
        result = run_sdd_git(
            ["clone", remote_url, str(workspace_sdd)],
            cwd=workspace_sdd.parent,
            op="sdd.clone.remote",
            timeout=network_git_timeout(),
            check=False,
            capture_output=True,
            text=True,
            env=clone_env,
        )
    except SddGitCommandTimeout as exc:
        return _handle_failed_sdd_clone(
            workspace_sdd,
            f"timed out cloning SDD store {remote_url} into {workspace_sdd}",
            strict=strict,
            cause=exc,
        )
    except Exception as exc:
        return _handle_failed_sdd_clone(
            workspace_sdd,
            f"failed to clone SDD store {remote_url} into {workspace_sdd}: "
            f"{str(exc) or type(exc).__name__}",
            strict=strict,
            cause=exc,
        )
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout or "").strip()
    return _handle_failed_sdd_clone(
        workspace_sdd,
        f"failed to clone SDD store {remote_url} into {workspace_sdd}: "
        f"{detail or f'git clone exited {result.returncode}'}",
        strict=strict,
    )


def _handle_failed_sdd_clone(
    workspace_sdd: Path,
    message: str,
    *,
    strict: bool,
    cause: Exception | None = None,
) -> bool:
    """Remove partial clone output and optionally fail the setup transaction."""

    try:
        if workspace_sdd.is_dir() and not workspace_sdd.is_symlink():
            shutil.rmtree(workspace_sdd)
        else:
            workspace_sdd.unlink(missing_ok=True)
    except OSError:
        _logger.warning(
            "Failed to clean partial SDD clone at %s",
            workspace_sdd,
            exc_info=True,
        )
    if strict:
        error = SddMaterializationError(message)
        if cause is not None:
            raise error from cause
        raise error
    _logger.warning(message, exc_info=cause is not None)
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
