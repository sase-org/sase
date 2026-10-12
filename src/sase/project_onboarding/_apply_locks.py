"""Cooperating locks for onboarding identity and checkout paths."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import time
from typing import Any

from sase.project_onboarding.journal import journals_dir

_LOCK_POLL_SECONDS = 0.05


class ApplyLockTimeout(TimeoutError):
    """A cooperating onboarding lock stayed held past the bounded wait."""


def _apply_identity_lock_path(identity_key: str) -> Path:
    """Return the cooperating apply lock path for *identity_key*.

    This is intentionally separate from the journal lock file: apply
    holds this lock across the whole plan-and-effects critical section
    while the journal helpers lock the journal file for each atomic
    update. Sharing one file would self-deadlock on ``flock``.
    """

    digest = hashlib.sha1(identity_key.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f".apply-{digest}.lock"


def _checkout_lock_path(checkout_dir: str) -> Path:
    normalized = str(Path(checkout_dir).expanduser())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return journals_dir() / f".checkout-{digest}.lock"


@contextmanager
def hold_apply_locks(
    identity_key: str, checkout_dir: str, *, timeout: float
) -> Iterator[None]:
    """Hold the identity and checkout locks in deterministic order."""

    wanted = {str(_apply_identity_lock_path(identity_key))}
    if checkout_dir.strip():
        wanted.add(str(_checkout_lock_path(checkout_dir)))
    handles: list[Any] = []
    try:
        deadline = time.monotonic() + max(0.0, timeout)
        for path_text in sorted(wanted):
            path = Path(path_text)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "ab")
            handles.append(handle)
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ApplyLockTimeout(path_text) from None
                    time.sleep(_LOCK_POLL_SECONDS)
                else:
                    break
        yield
    finally:
        for handle in reversed(handles):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                handle.close()


__all__ = ["ApplyLockTimeout", "_apply_identity_lock_path", "hold_apply_locks"]
