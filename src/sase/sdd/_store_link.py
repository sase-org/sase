"""Workspace-local clones for separate-repo SDD stores."""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from pathlib import Path
import shutil
import uuid

from sase.sdd._store_clone_ops import (
    clone_sdd_store,
    clone_sdd_store_from_primary,
    fast_forward_workspace_clone_from_primary,
    handle_failed_sdd_clone,
)
from sase.sdd._store_git import (
    git_remote_url as _git_remote_url,
    is_matching_store_clone as _is_matching_store_clone,
    paths_same_file as _paths_same_file,
    same_git_remote as _same_git_remote,
    set_sdd_origin as _set_sdd_origin,
)
from sase.sdd._store_integration import pull_sdd_clone
from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
from sase.sdd._store_types import (
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    SddStore,
)

_logger = logging.getLogger(__name__)

PrimaryWorkspaceResolver = Callable[[str, int], str]
StoreResolver = Callable[[str | Path, int], SddStore]

_clone_sdd_store = clone_sdd_store
_clone_sdd_store_from_primary = clone_sdd_store_from_primary
_fast_forward_workspace_clone_from_primary = fast_forward_workspace_clone_from_primary
_handle_failed_sdd_clone = handle_failed_sdd_clone
_pull_sdd_clone = pull_sdd_clone

__all__ = [
    "ensure_sidecar_sdd_clone",
    "ensure_workspace_sdd_clone",
    "is_matching_store_clone",
    "_clone_sdd_store",
    "_clone_sdd_store_from_primary",
    "_fast_forward_workspace_clone_from_primary",
    "_handle_failed_sdd_clone",
    "_pull_sdd_clone",
    "_replace_workspace_sdd_clone",
]


def ensure_sidecar_sdd_clone(
    clone_dir: Path,
    remote_url: str,
    *,
    reference_repo: Path | None = None,
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

        cloned = _clone_sdd_store(
            remote_url,
            clone_dir,
            reference_repo=reference_repo,
            strict=strict,
        )
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
            if is_materialized_record(read_sdd_store_record(primary)):
                raise SddMaterializationError(
                    f"could not create workspace SDD sidecar clone at {workspace_sdd}"
                )
            raise SddMaterializationError(_no_materialized_record_message(primary))
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


def _no_materialized_record_message(primary: Path) -> str:
    """Describe the ``sase repo init`` remedy for an unconnected SDD store."""

    from sase.content_layout import (
        resolve_project_config_read_path,
        resolve_project_config_write_path,
    )
    from sase.project_management import project_management_status

    config_path = resolve_project_config_read_path(primary)
    if config_path is None:
        config_path = resolve_project_config_write_path(primary)
    management = project_management_status(config_path)

    message = (
        f"{primary}: this project's SDD store has never been initialized on "
        "this machine; run `sase repo init` in that checkout to connect it"
    )
    if management.error is not None or not management.is_sase_managed:
        message += f" (set is_sase_managed: true in {primary}'s sase/sase.yml first)"
    return message


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


is_matching_store_clone = _is_matching_store_clone
