"""Git clone operations for provider-owned SDD stores."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import time

from sase._git_remote import is_http_git_remote
from sase.sdd._store_git import (
    git_remote_url as _git_remote_url,
    paths_same_file as _paths_same_file,
    same_git_remote as _same_git_remote,
)
from sase.sdd._store_types import SddMaterializationError

_logger = logging.getLogger(__name__)

_REMOTE_CLONE_RETRY_DELAYS = (0.25, 1.0, 2.0)
_TRANSIENT_REMOTE_CLONE_ERRORS = (
    "broken pipe",
    "closed by remote host",
    "connection refused",
    "connection reset",
    "connection timed out",
    "could not resolve hostname",
    "early eof",
    "invalid index-pack output",
    "network is unreachable",
    "no route to host",
    "remote end hung up unexpectedly",
    "unexpected disconnect",
)


def clone_sdd_store(
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference_repo: Path | None = None,
    strict: bool = False,
) -> bool:
    if is_http_git_remote(remote_url):
        return handle_failed_sdd_clone(
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

    clone_env = os.environ.copy()
    clone_env["GIT_TERMINAL_PROMPT"] = "0"
    clone_args = ["clone"]
    reference = _matching_clone_reference(reference_repo, remote_url)
    if reference is not None:
        # Borrow matching local objects to reduce the remote transfer, then
        # dissociate so numbered workspaces never depend on the reference
        # clone remaining at the same path. Refs still come from the recorded
        # remote, so unpublished commits in the reference cannot leak in.
        clone_args.extend(["--reference-if-able", str(reference), "--dissociate"])
    clone_args.extend([remote_url, str(workspace_sdd)])

    for attempt in range(len(_REMOTE_CLONE_RETRY_DELAYS) + 1):
        try:
            # Clone builds a fresh checkout with no existing index.lock to recover.
            result = run_sdd_git(
                clone_args,
                cwd=workspace_sdd.parent,
                op="sdd.clone.remote",
                timeout=network_git_timeout(),
                check=False,
                capture_output=True,
                text=True,
                env=clone_env,
            )
        except SddGitCommandTimeout as exc:
            return handle_failed_sdd_clone(
                workspace_sdd,
                f"timed out cloning SDD store {remote_url} into {workspace_sdd}",
                strict=strict,
                cause=exc,
            )
        except Exception as exc:
            return handle_failed_sdd_clone(
                workspace_sdd,
                f"failed to clone SDD store {remote_url} into {workspace_sdd}: "
                f"{str(exc) or type(exc).__name__}",
                strict=strict,
                cause=exc,
            )
        if result.returncode == 0:
            return True

        detail = (result.stderr or result.stdout or "").strip()
        if not _is_transient_remote_clone_failure(detail) or attempt >= len(
            _REMOTE_CLONE_RETRY_DELAYS
        ):
            return handle_failed_sdd_clone(
                workspace_sdd,
                f"failed to clone SDD store {remote_url} into {workspace_sdd}: "
                f"{detail or f'git clone exited {result.returncode}'}",
                strict=strict,
            )

        _remove_partial_sdd_clone(workspace_sdd)
        delay = _REMOTE_CLONE_RETRY_DELAYS[attempt]
        _logger.warning(
            "Transient failure cloning SDD store %s into %s; retrying in "
            "%.2fs (attempt %d/%d): %s",
            remote_url,
            workspace_sdd,
            delay,
            attempt + 2,
            len(_REMOTE_CLONE_RETRY_DELAYS) + 1,
            detail,
        )
        time.sleep(delay)

    raise AssertionError("remote clone retry loop did not return")


def _matching_clone_reference(
    reference_repo: Path | None,
    remote_url: str,
) -> Path | None:
    """Return a valid matching object reference without trusting its refs."""

    if reference_repo is None:
        return None
    reference = reference_repo.expanduser()
    if not (reference / ".git").is_dir():
        return None
    reference_remote = _git_remote_url(reference)
    if reference_remote is None or not _same_git_remote(reference_remote, remote_url):
        return None
    return reference


def _is_transient_remote_clone_failure(detail: str) -> bool:
    normalized = detail.casefold()
    return any(marker in normalized for marker in _TRANSIENT_REMOTE_CLONE_ERRORS)


def _remove_partial_sdd_clone(workspace_sdd: Path) -> None:
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


def handle_failed_sdd_clone(
    workspace_sdd: Path,
    message: str,
    *,
    strict: bool,
    cause: Exception | None = None,
) -> bool:
    """Remove partial clone output and optionally fail the setup transaction."""

    _remove_partial_sdd_clone(workspace_sdd)
    if strict:
        error = SddMaterializationError(message)
        if cause is not None:
            raise error from cause
        raise error
    _logger.warning(message, exc_info=cause is not None)
    return False


def clone_sdd_store_from_primary(primary_sdd: Path, workspace_sdd: Path) -> bool:
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
        # Clone builds a fresh checkout with no existing index.lock to recover.
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


def fast_forward_workspace_clone_from_primary(
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
    )
    from sase.sdd._git_contention import run_sdd_git_write

    try:
        result = run_sdd_git_write(
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
