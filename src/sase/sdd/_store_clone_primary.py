"""Local-primary SDD clone and refresh operations."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sase.sdd._store_clone_common import deadline_timeout, remove_partial_sdd_clone
from sase.sdd._store_clone_transaction import (
    ClonePublicationError,
    CloneTransactionTimeout,
    clone_materialization_transaction,
    valid_published_sdd_clone,
    validate_staged_sdd_clone,
)
from sase.sdd._store_git import paths_same_file, set_sdd_origin

_logger = logging.getLogger(__name__)


def clone_sdd_store_from_primary(
    primary_sdd: Path,
    workspace_sdd: Path,
    *,
    deadline: float | None = None,
    remote_url: str | None = None,
    publish: bool = True,
) -> bool:
    if not (primary_sdd / ".git").is_dir():
        return False
    if paths_same_file(primary_sdd, workspace_sdd):
        return workspace_sdd.is_dir()

    workspace_sdd = workspace_sdd.expanduser()
    expected_remote = remote_url or str(primary_sdd)
    if publish:
        try:
            with clone_materialization_transaction(
                workspace_sdd,
                deadline=deadline,
            ) as transaction:
                if os.path.lexists(workspace_sdd):
                    return valid_published_sdd_clone(
                        workspace_sdd,
                        expected_remote=expected_remote,
                        deadline=deadline,
                    )
                cloned = clone_sdd_store_from_primary(
                    primary_sdd,
                    transaction.clone_path,
                    deadline=deadline,
                    remote_url=remote_url,
                    publish=False,
                )
                if not cloned:
                    return False
                try:
                    transaction.publish(
                        expected_remote=expected_remote,
                        deadline=deadline,
                    )
                except ClonePublicationError:
                    _logger.warning(
                        "Failed to publish workspace SDD store %s cloned from "
                        "primary %s",
                        workspace_sdd,
                        primary_sdd,
                        exc_info=True,
                    )
                    return False
                return True
        except CloneTransactionTimeout:
            _logger.warning(
                "Timed out waiting to materialize workspace SDD store %s from "
                "primary %s",
                workspace_sdd,
                primary_sdd,
                exc_info=True,
            )
            return False

    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        timeout = deadline_timeout(network_git_timeout(), deadline)
        if timeout <= 0.0:
            return False
        result = run_sdd_git(
            ["clone", str(primary_sdd), str(workspace_sdd)],
            cwd=workspace_sdd.parent,
            op="sdd.clone.primary",
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and remote_url:
            set_sdd_origin(workspace_sdd, remote_url)
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
        try:
            validate_staged_sdd_clone(
                workspace_sdd,
                expected_remote=expected_remote,
                deadline=deadline,
            )
        except ClonePublicationError:
            remove_partial_sdd_clone(workspace_sdd)
            _logger.warning(
                "Cloned workspace SDD store %s from primary %s failed validation",
                workspace_sdd,
                primary_sdd,
                exc_info=True,
            )
            return False
        return True
    detail = (result.stderr or result.stdout or "").strip()
    _logger.warning(
        "Failed to clone workspace SDD store %s from primary %s: %s",
        workspace_sdd,
        primary_sdd,
        detail or f"git clone exited {result.returncode}",
    )
    return False


def fast_forward_workspace_clone_from_primary(
    workspace_sdd: Path, primary_sdd: Path, *, deadline: float | None = None
) -> None:
    """Best-effort fast-forward a workspace store clone from the primary store."""

    if not (primary_sdd / ".git").is_dir():
        return
    from sase.sdd._commit import SddGitCommandTimeout, network_git_timeout
    from sase.sdd._git_contention import run_sdd_git_write

    try:
        timeout = deadline_timeout(network_git_timeout(), deadline)
        if timeout <= 0.0:
            return
        result = run_sdd_git_write(
            ["pull", "--ff-only", str(primary_sdd)],
            cwd=workspace_sdd,
            op="sdd.clone.fast_forward",
            timeout=timeout,
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
