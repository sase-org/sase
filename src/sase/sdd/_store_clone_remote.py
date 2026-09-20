"""Remote SDD store cloning with retries and host admission control."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sase._git_remote import is_http_git_remote
from sase.core.retryability_facade import is_retryable_git_clone_failure
from sase.core.retryability_wire import RETRY_OPERATION_GIT_CLONE
from sase.sdd._store_clone_admission import (
    RemoteCloneAdmissionTimeout,
    remote_clone_admission,
)
from sase.sdd._store_clone_common import (
    deadline_timeout,
    handle_failed_sdd_clone,
    remove_partial_sdd_clone,
    sleep_before_retry,
)
from sase.sdd._store_git import git_remote_url, same_git_remote

_logger = logging.getLogger(__name__)

_REMOTE_CLONE_RETRY_DELAYS = (0.25, 1.0, 2.0)
_REMOTE_CLONE_TIMEOUT_GROWTH = 0.5
_MAX_RETRIES_WITHOUT_REFERENCE = 1


def clone_sdd_store_to_path(
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference_repo: Path | None = None,
    strict: bool = False,
    deadline: float | None = None,
    canonical_sdd: Path | None = None,
) -> bool:
    """Clone a remote into an unpublished destination, retrying transient failures."""

    telemetry_sdd = workspace_sdd if canonical_sdd is None else canonical_sdd
    if is_http_git_remote(remote_url):
        return handle_failed_sdd_clone(
            telemetry_sdd,
            f"refusing HTTP(S) SDD sidecar remote {remote_url!r}; "
            "materialization requires an SSH or local Git remote and Git was "
            "not invoked",
            strict=strict,
            cleanup_path=workspace_sdd,
        )

    from sase.sdd._commit import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    clone_env = os.environ.copy()
    clone_env["GIT_TERMINAL_PROMPT"] = "0"
    reference = _matching_clone_reference(reference_repo, remote_url)
    clone_args = _remote_clone_args(remote_url, workspace_sdd, reference=reference)
    retries_without_reference = 0
    max_attempts = len(_REMOTE_CLONE_RETRY_DELAYS) + 1
    base_timeout = network_git_timeout()
    for attempt in range(max_attempts):
        attempt_telemetry = _clone_attempt_telemetry(
            telemetry_sdd,
            remote_url=remote_url,
            attempt=attempt,
            max_attempts=max_attempts,
            reference=reference,
            clone_path=workspace_sdd,
        )
        timeout = _clone_attempt_timeout(base_timeout, attempt, deadline)
        if timeout <= 0.0:
            return handle_failed_sdd_clone(
                telemetry_sdd,
                f"deadline expired before cloning SDD store {remote_url} into "
                f"{telemetry_sdd}",
                strict=strict,
                transient=True,
                cleanup_path=workspace_sdd,
            )
        try:
            with remote_clone_admission(remote_url, telemetry_sdd, deadline=deadline):
                timeout = deadline_timeout(timeout, deadline)
                if timeout <= 0.0:
                    raise RemoteCloneAdmissionTimeout(
                        "deadline expired after acquiring SDD remote clone permit "
                        f"for {remote_url} into {telemetry_sdd}"
                    )
                result = run_sdd_git(
                    clone_args,
                    cwd=workspace_sdd.parent,
                    op="sdd.clone.remote",
                    timeout=timeout,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=clone_env,
                    telemetry=attempt_telemetry,
                    retryability_operation_kind=RETRY_OPERATION_GIT_CLONE,
                )
        except RemoteCloneAdmissionTimeout as exc:
            return handle_failed_sdd_clone(
                telemetry_sdd,
                str(exc),
                strict=strict,
                transient=True,
                cause=exc,
                cleanup_path=workspace_sdd,
            )
        except SddGitCommandTimeout as exc:
            if _can_retry_without_reference(
                reference, retries_without_reference, attempt
            ):
                remove_partial_sdd_clone(workspace_sdd)
                retries_without_reference += 1
                _logger.warning(
                    "Timed out cloning SDD store %s into %s with local object "
                    "reference %s; retrying without the reference",
                    remote_url,
                    telemetry_sdd,
                    reference,
                )
                reference = None
                clone_args = _remote_clone_args(
                    remote_url, workspace_sdd, reference=None
                )
                continue
            if attempt >= len(_REMOTE_CLONE_RETRY_DELAYS):
                return handle_failed_sdd_clone(
                    telemetry_sdd,
                    f"timed out cloning SDD store {remote_url} into {telemetry_sdd}",
                    strict=strict,
                    cause=exc,
                    transient=True,
                    cleanup_path=workspace_sdd,
                )
            remove_partial_sdd_clone(workspace_sdd)
            delay = _REMOTE_CLONE_RETRY_DELAYS[attempt]
            _logger.warning(
                "Timed out cloning SDD store %s into %s after %.1fs; retrying "
                "in %.2fs (attempt %d/%d)",
                remote_url,
                telemetry_sdd,
                timeout,
                delay,
                attempt + 2,
                max_attempts,
            )
            if not sleep_before_retry(delay, deadline):
                return handle_failed_sdd_clone(
                    telemetry_sdd,
                    f"deadline expired before retrying SDD clone {remote_url} into "
                    f"{telemetry_sdd}",
                    strict=strict,
                    transient=True,
                    cleanup_path=workspace_sdd,
                )
            continue
        except Exception as exc:
            return handle_failed_sdd_clone(
                telemetry_sdd,
                f"failed to clone SDD store {remote_url} into {telemetry_sdd}: "
                f"{str(exc) or type(exc).__name__}",
                strict=strict,
                cause=exc,
                cleanup_path=workspace_sdd,
            )
        if result.returncode == 0:
            return True

        detail = (result.stderr or result.stdout or "").strip()
        if _can_retry_without_reference(reference, retries_without_reference, attempt):
            remove_partial_sdd_clone(workspace_sdd)
            retries_without_reference += 1
            _logger.warning(
                "Failed cloning SDD store %s into %s with local object "
                "reference %s; retrying without the reference: %s",
                remote_url,
                telemetry_sdd,
                reference,
                detail or f"git clone exited {result.returncode}",
            )
            reference = None
            clone_args = _remote_clone_args(remote_url, workspace_sdd, reference=None)
            continue
        transient = is_transient_remote_clone_failure(detail)
        if not transient or attempt >= len(_REMOTE_CLONE_RETRY_DELAYS):
            return handle_failed_sdd_clone(
                telemetry_sdd,
                f"failed to clone SDD store {remote_url} into {telemetry_sdd}: "
                f"{detail or f'git clone exited {result.returncode}'}",
                strict=strict,
                transient=transient,
                cleanup_path=workspace_sdd,
            )
        remove_partial_sdd_clone(workspace_sdd)
        delay = _REMOTE_CLONE_RETRY_DELAYS[attempt]
        _logger.warning(
            "Transient failure cloning SDD store %s into %s; retrying in "
            "%.2fs (attempt %d/%d): %s",
            remote_url,
            telemetry_sdd,
            delay,
            attempt + 2,
            max_attempts,
            detail,
        )
        if not sleep_before_retry(delay, deadline):
            return handle_failed_sdd_clone(
                telemetry_sdd,
                f"deadline expired before retrying SDD clone {remote_url} into "
                f"{telemetry_sdd}",
                strict=strict,
                transient=True,
                cleanup_path=workspace_sdd,
            )
    raise AssertionError("remote clone retry loop did not return")


def _remote_clone_args(
    remote_url: str, workspace_sdd: Path, *, reference: Path | None
) -> list[str]:
    clone_args = ["clone"]
    if reference is not None:
        clone_args.extend(["--reference-if-able", str(reference), "--dissociate"])
    clone_args.extend([remote_url, str(workspace_sdd)])
    return clone_args


def _clone_attempt_telemetry(
    workspace_sdd: Path,
    *,
    remote_url: str,
    attempt: int,
    max_attempts: int,
    reference: Path | None,
    clone_path: Path | None = None,
) -> dict[str, object]:
    telemetry: dict[str, object] = {
        "retry_attempt_index": attempt,
        "retry_attempt_ordinal": attempt + 1,
        "retry_attempts_total": max_attempts,
        "reference_repo_used": reference is not None,
        "sdd_store_path": str(workspace_sdd),
        "sdd_store_name": workspace_sdd.name,
        "sdd_remote_url": remote_url,
    }
    if clone_path is not None:
        telemetry["sdd_clone_stage_path"] = str(clone_path)
    return telemetry


def _matching_clone_reference(
    reference_repo: Path | None, remote_url: str
) -> Path | None:
    """Return a valid matching object reference without trusting its refs."""

    if reference_repo is None:
        return None
    reference = reference_repo.expanduser()
    if not (reference / ".git").is_dir():
        return None
    reference_remote = git_remote_url(reference)
    if reference_remote is None or not same_git_remote(reference_remote, remote_url):
        return None
    return reference


def is_transient_remote_clone_failure(detail: str) -> bool:
    return is_retryable_git_clone_failure(detail)


def _clone_attempt_timeout(
    base_timeout: float, attempt: int, deadline: float | None
) -> float:
    timeout = max(0.0, base_timeout) * (1.0 + attempt * _REMOTE_CLONE_TIMEOUT_GROWTH)
    return deadline_timeout(timeout, deadline)


def _can_retry_without_reference(
    reference: Path | None, retries_without_reference: int, attempt: int
) -> bool:
    return (
        reference is not None
        and retries_without_reference < _MAX_RETRIES_WITHOUT_REFERENCE
        and attempt < len(_REMOTE_CLONE_RETRY_DELAYS)
    )
