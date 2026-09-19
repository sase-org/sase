"""Host-wide admission control for remote SDD clones."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import logging
import os
from pathlib import Path
import time

from sase._git_remote import parse_hosted_git_remote

_logger = logging.getLogger(__name__)

ENV_REMOTE_CLONE_CONCURRENCY = "SASE_SDD_REMOTE_CLONE_CONCURRENCY"
DEFAULT_REMOTE_CLONE_CONCURRENCY = 1
_REMOTE_CLONE_ADMISSION_POLL_SECONDS = 0.1


class RemoteCloneAdmissionTimeout(RuntimeError):
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
def remote_clone_admission(
    remote_url: str,
    workspace_sdd: Path,
    *,
    deadline: float | None,
) -> Iterator[None]:
    permit: _RemoteClonePermit | None = None
    if parse_hosted_git_remote(remote_url) is not None:
        permit = acquire_remote_clone_permit(
            remote_url,
            workspace_sdd,
            deadline=deadline,
        )
    try:
        yield
    finally:
        if permit is not None:
            permit.close()


def configured_remote_clone_concurrency() -> int:
    """Return the host-wide remote clone concurrency bound."""

    raw = os.environ.get(ENV_REMOTE_CLONE_CONCURRENCY)
    if raw is None:
        return DEFAULT_REMOTE_CLONE_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_REMOTE_CLONE_CONCURRENCY
    return value if value > 0 else DEFAULT_REMOTE_CLONE_CONCURRENCY


def remote_clone_lock_dir() -> Path | None:
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


def acquire_remote_clone_permit(
    remote_url: str,
    workspace_sdd: Path,
    *,
    deadline: float | None,
) -> _RemoteClonePermit | None:
    lock_dir = remote_clone_lock_dir()
    if lock_dir is None:
        return None

    limit = configured_remote_clone_concurrency()
    while True:
        for index in range(limit):
            permit = try_remote_clone_permit(lock_dir / f"slot-{index}.lock")
            if permit is not None:
                return permit

        if deadline is not None and time.monotonic() >= deadline:
            raise RemoteCloneAdmissionTimeout(
                f"timed out waiting for SDD remote clone permit before cloning "
                f"{remote_url} into {workspace_sdd}; "
                f"host clone concurrency limit is {limit}"
            )
        time.sleep(_REMOTE_CLONE_ADMISSION_POLL_SECONDS)


def try_remote_clone_permit(path: Path) -> _RemoteClonePermit | None:
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
