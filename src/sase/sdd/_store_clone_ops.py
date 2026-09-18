"""Git clone operations for provider-owned SDD stores."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path
import shutil
import time

from sase._git_remote import is_http_git_remote, parse_hosted_git_remote
from sase.core.retryability_facade import is_retryable_git_clone_failure
from sase.core.retryability_wire import RETRY_OPERATION_GIT_CLONE
from sase.sdd._store_clone_transaction import (
    ClonePublicationError as _ClonePublicationError,
    CloneTransactionTimeout as _CloneTransactionTimeout,
    clone_materialization_transaction as _clone_materialization_transaction,
    valid_published_sdd_clone as _valid_published_sdd_clone,
    validate_staged_sdd_clone as _validate_staged_sdd_clone,
)
from sase.sdd._store_git import (
    git_remote_url as _git_remote_url,
    paths_same_file as _paths_same_file,
    same_git_remote as _same_git_remote,
    set_sdd_origin as _set_sdd_origin,
)
from sase.sdd._store_types import (
    SddMaterializationError,
    SddTransientMaterializationError,
)

_logger = logging.getLogger(__name__)

ENV_REMOTE_CLONE_CONCURRENCY = "SASE_SDD_REMOTE_CLONE_CONCURRENCY"
DEFAULT_REMOTE_CLONE_CONCURRENCY = 1
_REMOTE_CLONE_ADMISSION_POLL_SECONDS = 0.1
_REMOTE_CLONE_RETRY_DELAYS = (0.25, 1.0, 2.0)
_REMOTE_CLONE_TIMEOUT_GROWTH = 0.5
_MAX_RETRIES_WITHOUT_REFERENCE = 1


def clone_sdd_store(
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference_repo: Path | None = None,
    strict: bool = False,
    deadline: float | None = None,
) -> bool:
    workspace_sdd = workspace_sdd.expanduser()
    if is_http_git_remote(remote_url):
        return handle_failed_sdd_clone(
            workspace_sdd,
            f"refusing HTTP(S) SDD sidecar remote {remote_url!r}; "
            "materialization requires an SSH or local Git remote and Git was "
            "not invoked",
            strict=strict,
            cleanup_path=None,
        )

    try:
        with _clone_materialization_transaction(
            workspace_sdd,
            deadline=deadline,
        ) as transaction:
            if os.path.lexists(workspace_sdd):
                if _valid_published_sdd_clone(
                    workspace_sdd,
                    expected_remote=remote_url,
                    deadline=deadline,
                ):
                    return True
                return handle_failed_sdd_clone(
                    workspace_sdd,
                    f"refusing to overwrite existing SDD store at {workspace_sdd}; "
                    "the concurrently materialized destination is not a healthy "
                    "clone of the configured remote",
                    strict=strict,
                    cleanup_path=transaction.clone_path,
                )

            cloned = _clone_sdd_store_to_path(
                remote_url,
                transaction.clone_path,
                reference_repo=reference_repo,
                strict=strict,
                deadline=deadline,
                canonical_sdd=workspace_sdd,
            )
            if not cloned:
                return False
            try:
                transaction.publish(
                    expected_remote=remote_url,
                    deadline=deadline,
                )
            except _ClonePublicationError as exc:
                return handle_failed_sdd_clone(
                    workspace_sdd,
                    str(exc),
                    strict=strict,
                    cause=exc,
                    cleanup_path=transaction.clone_path,
                )
            return True
    except _CloneTransactionTimeout as exc:
        return handle_failed_sdd_clone(
            workspace_sdd,
            str(exc),
            strict=strict,
            cause=exc,
            transient=True,
            cleanup_path=None,
        )


def _clone_sdd_store_to_path(
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference_repo: Path | None = None,
    strict: bool = False,
    deadline: float | None = None,
    canonical_sdd: Path | None = None,
) -> bool:
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
            # Clone builds a fresh checkout with no existing index.lock to recover.
            with _remote_clone_admission(remote_url, telemetry_sdd, deadline=deadline):
                timeout = _deadline_timeout(timeout, deadline)
                if timeout <= 0.0:
                    raise _RemoteCloneAdmissionTimeout(
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
        except _RemoteCloneAdmissionTimeout as exc:
            return handle_failed_sdd_clone(
                telemetry_sdd,
                str(exc),
                strict=strict,
                transient=True,
                cause=exc,
                cleanup_path=workspace_sdd,
            )
        except SddGitCommandTimeout as exc:
            can_retry_without_reference = (
                reference is not None
                and retries_without_reference < _MAX_RETRIES_WITHOUT_REFERENCE
                and attempt < len(_REMOTE_CLONE_RETRY_DELAYS)
            )
            if can_retry_without_reference:
                _remove_partial_sdd_clone(workspace_sdd)
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
                    remote_url, workspace_sdd, reference=reference
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

            _remove_partial_sdd_clone(workspace_sdd)
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
            if not _sleep_before_retry(delay, deadline):
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
        can_retry_without_reference = (
            reference is not None
            and retries_without_reference < _MAX_RETRIES_WITHOUT_REFERENCE
            and attempt < len(_REMOTE_CLONE_RETRY_DELAYS)
        )
        if can_retry_without_reference:
            _remove_partial_sdd_clone(workspace_sdd)
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
            clone_args = _remote_clone_args(
                remote_url, workspace_sdd, reference=reference
            )
            continue

        if not _is_transient_remote_clone_failure(detail) or attempt >= len(
            _REMOTE_CLONE_RETRY_DELAYS
        ):
            return handle_failed_sdd_clone(
                telemetry_sdd,
                f"failed to clone SDD store {remote_url} into {telemetry_sdd}: "
                f"{detail or f'git clone exited {result.returncode}'}",
                strict=strict,
                transient=_is_transient_remote_clone_failure(detail),
                cleanup_path=workspace_sdd,
            )

        _remove_partial_sdd_clone(workspace_sdd)
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
        if not _sleep_before_retry(delay, deadline):
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
    remote_url: str,
    workspace_sdd: Path,
    *,
    reference: Path | None,
) -> list[str]:
    clone_args = ["clone"]
    if reference is not None:
        # Borrow matching local objects to reduce the remote transfer, then
        # dissociate so numbered workspaces never depend on the reference
        # clone remaining at the same path. Refs still come from the recorded
        # remote, so unpublished commits in the reference cannot leak in.
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
    return is_retryable_git_clone_failure(detail)


@contextmanager
def staged_sdd_clone_replacement(
    workspace_sdd: Path,
    primary_sdd: Path,
    remote_url: str | None,
    *,
    deadline: float | None = None,
) -> Iterator[Path]:
    """Yield a validated staged clone for replacing an existing workspace path."""

    expected_remote = remote_url or str(primary_sdd)
    with _clone_materialization_transaction(
        workspace_sdd,
        deadline=deadline,
    ) as transaction:
        cloned = clone_sdd_store_from_primary(
            primary_sdd,
            transaction.clone_path,
            deadline=deadline,
            remote_url=remote_url,
            publish=False,
        )
        if not cloned and remote_url:
            cloned = _clone_sdd_store_to_path(
                remote_url,
                transaction.clone_path,
                strict=False,
                deadline=deadline,
                canonical_sdd=workspace_sdd,
            )
        if not cloned:
            raise SddMaterializationError(
                f"could not create replacement SDD sidecar clone for {workspace_sdd}"
            )
        _validate_staged_sdd_clone(
            transaction.clone_path,
            expected_remote=expected_remote,
            deadline=deadline,
        )
        yield transaction.clone_path


class _RemoteCloneAdmissionTimeout(RuntimeError):
    """Raised when the host remote-clone pool stays full until the deadline."""


class _RemoteClonePermit:
    def __init__(self, fd: int, path: Path) -> None:
        self._fd = fd
        self.path = path

    def close(self) -> None:
        fd = self._fd
        self._fd = -1
        if fd < 0:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def _remote_clone_admission(
    remote_url: str,
    workspace_sdd: Path,
    *,
    deadline: float | None,
) -> Iterator[None]:
    permit: _RemoteClonePermit | None = None
    if _should_bound_remote_clone(remote_url):
        permit = _acquire_remote_clone_permit(
            remote_url,
            workspace_sdd,
            deadline=deadline,
        )
    try:
        yield
    finally:
        if permit is not None:
            permit.close()


def _should_bound_remote_clone(remote_url: str) -> bool:
    return parse_hosted_git_remote(remote_url) is not None


def _configured_remote_clone_concurrency() -> int:
    """Return the host-wide remote clone concurrency bound."""

    raw = os.environ.get(ENV_REMOTE_CLONE_CONCURRENCY)
    if raw is None:
        return DEFAULT_REMOTE_CLONE_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_REMOTE_CLONE_CONCURRENCY
    return value if value > 0 else DEFAULT_REMOTE_CLONE_CONCURRENCY


def _remote_clone_lock_dir() -> Path | None:
    try:
        from sase.core.paths import get_sase_managed_tmpdir

        return Path(get_sase_managed_tmpdir("sdd-remote-clone-pool"))
    except Exception:
        _logger.warning(
            "Unable to resolve SDD remote clone admission directory; "
            "continuing without the host-wide clone bound",
            exc_info=True,
        )
        return None


def _acquire_remote_clone_permit(
    remote_url: str,
    workspace_sdd: Path,
    *,
    deadline: float | None,
) -> _RemoteClonePermit | None:
    lock_dir = _remote_clone_lock_dir()
    if lock_dir is None:
        return None

    limit = _configured_remote_clone_concurrency()
    while True:
        for index in range(limit):
            permit = _try_remote_clone_permit(lock_dir / f"slot-{index}.lock")
            if permit is not None:
                return permit

        if deadline is not None and time.monotonic() >= deadline:
            raise _RemoteCloneAdmissionTimeout(
                f"timed out waiting for SDD remote clone permit before cloning "
                f"{remote_url} into {workspace_sdd}; "
                f"host clone concurrency limit is {limit}"
            )
        time.sleep(_REMOTE_CLONE_ADMISSION_POLL_SECONDS)


def _try_remote_clone_permit(path: Path) -> _RemoteClonePermit | None:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except OSError:
        os.close(fd)
        raise
    os.ftruncate(fd, 0)
    os.write(fd, f"pid={os.getpid()} acquired_at={time.time():.6f}\n".encode())
    return _RemoteClonePermit(fd, path)


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
    transient: bool = False,
    cleanup_path: Path | None = None,
) -> bool:
    """Remove partial clone output and optionally fail the setup transaction."""

    if cleanup_path is not None:
        _remove_partial_sdd_clone(cleanup_path)
    if strict:
        error_cls = (
            SddTransientMaterializationError if transient else SddMaterializationError
        )
        error = error_cls(message)
        if cause is not None:
            raise error from cause
        raise error
    _logger.warning(message, exc_info=cause is not None)
    return False


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
    if _paths_same_file(primary_sdd, workspace_sdd):
        return workspace_sdd.is_dir()

    workspace_sdd = workspace_sdd.expanduser()
    expected_remote = remote_url or str(primary_sdd)
    if publish:
        try:
            with _clone_materialization_transaction(
                workspace_sdd,
                deadline=deadline,
            ) as transaction:
                if os.path.lexists(workspace_sdd):
                    return _valid_published_sdd_clone(
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
                except _ClonePublicationError:
                    _logger.warning(
                        "Failed to publish workspace SDD store %s cloned from "
                        "primary %s",
                        workspace_sdd,
                        primary_sdd,
                        exc_info=True,
                    )
                    return False
                return True
        except _CloneTransactionTimeout:
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
        timeout = _deadline_timeout(network_git_timeout(), deadline)
        if timeout <= 0.0:
            return False
        # Clone builds a fresh checkout with no existing index.lock to recover.
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
            _set_sdd_origin(workspace_sdd, remote_url)
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
            _validate_staged_sdd_clone(
                workspace_sdd,
                expected_remote=expected_remote,
                deadline=deadline,
            )
        except _ClonePublicationError:
            _remove_partial_sdd_clone(workspace_sdd)
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
        timeout = _deadline_timeout(network_git_timeout(), deadline)
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


def _deadline_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    return min(max(0.0, default), max(0.0, deadline - time.monotonic()))


def _clone_attempt_timeout(
    base_timeout: float, attempt: int, deadline: float | None
) -> float:
    timeout = max(0.0, base_timeout) * (1.0 + attempt * _REMOTE_CLONE_TIMEOUT_GROWTH)
    return _deadline_timeout(timeout, deadline)


def _sleep_before_retry(delay: float, deadline: float | None) -> bool:
    wait = max(0.0, delay)
    if deadline is not None:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0.0:
            return False
        wait = min(wait, remaining)
    time.sleep(wait)
    return deadline is None or time.monotonic() < deadline
