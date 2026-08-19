"""The token files themselves: one lock file per unit of host-wide parallelism.

Split out of :mod:`tests._suite_gate`. The pool is a directory of numbered
lock files plus a ``pool.lock`` that records the capacity they were created
under. A token is held by holding its ``flock``, which is why the pool is
crash-safe: a holder that dies never has to clean up after itself.

Nothing here takes the pool-wide lock;
:class:`tests._suite_gate_lease.WorkerTokenLease` does that around whichever of
these it calls.
"""

from __future__ import annotations

import errno
import fcntl
import json
import time
from pathlib import Path
from typing import IO, Any


POOL_FILE_NAME = "pool.lock"


def read_pool_capacity(pool_file: IO[str]) -> int | None:
    """Return the capacity the live pool was created with, if it is readable."""
    pool_file.seek(0)
    try:
        parsed: Any = json.load(pool_file)
        capacity = int(parsed["capacity"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return capacity if capacity > 0 else None


def write_pool_capacity(pool_file: IO[str], capacity: int, *, explicit: bool) -> None:
    """Record the capacity a newly empty pool is being restarted under."""
    metadata = {
        "capacity": capacity,
        "explicit": explicit,
        "updated": time.time(),
    }
    pool_file.seek(0)
    pool_file.truncate()
    json.dump(metadata, pool_file, sort_keys=True)
    pool_file.write("\n")
    pool_file.flush()


def _token_path(directory: Path, token_number: int) -> Path:
    """Return the lock file backing one numbered token."""
    return directory / f"token-{token_number:03d}.lock"


def scan_active_holders(directory: Path, limit: int) -> dict[Path, str]:
    """Return the metadata of every token below ``limit`` somebody else holds."""
    holders: dict[Path, str] = {}
    for token_number in range(limit):
        token_path = _token_path(directory, token_number)
        token_file, metadata = _try_acquire_token(token_path)
        if token_file is None:
            holders[token_path] = metadata
        else:
            token_file.close()
    return holders


def try_acquire_tokens(
    directory: Path, budget: int, ceiling: int
) -> tuple[list[IO[str]], dict[Path, str]]:
    """Take up to ``ceiling`` free tokens, reporting who holds the rest."""
    token_files: list[IO[str]] = []
    holders: dict[Path, str] = {}
    for token_number in range(budget):
        token_path = _token_path(directory, token_number)
        token_file, metadata = _try_acquire_token(token_path)
        if token_file is None:
            holders[token_path] = metadata
            continue
        token_files.append(token_file)
        if len(token_files) == ceiling:
            break
    return token_files, holders


def _try_acquire_token(token_path: Path) -> tuple[IO[str] | None, str]:
    """Take one token, or return the holder's metadata when it is locked."""
    token_file = token_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(token_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EAGAIN):
            token_file.close()
            raise
        token_file.seek(0)
        metadata = token_file.read()
        token_file.close()
        return None, metadata
    return token_file, ""


def release_token_files(token_files: list[IO[str]]) -> None:
    """Unlock and close every token, re-raising the first failure at the end."""
    first_error: BaseException | None = None
    for token_file in token_files:
        try:
            fcntl.flock(token_file.fileno(), fcntl.LOCK_UN)
        except BaseException as error:  # pragma: no cover - defensive cleanup
            first_error = first_error or error
        try:
            token_file.close()
        except BaseException as error:  # pragma: no cover - defensive cleanup
            first_error = first_error or error
    if first_error is not None:
        raise first_error


def started_from_token_files(token_files: list[IO[str]]) -> float | None:
    """Recover a grant's start time from its tokens, for an adopted lease."""
    for token_file in token_files:
        try:
            token_file.seek(0)
            parsed: Any = json.load(token_file)
            return float(parsed["started"])
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def refresh_token_heartbeats(
    token_files: list[IO[str]], heartbeat: float, progress: int
) -> None:
    """Rewrite each token's record in place with the caller's latest progress.

    Best-effort by design: a token whose record is unreadable or unwritable is
    skipped rather than failing the run, because the sidecar written by
    :func:`tests._suite_gate_progress.write_progress_sidecar` already carries
    the same heartbeat.
    """
    for token_file in token_files:
        try:
            token_file.seek(0)
            parsed: Any = json.load(token_file)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        parsed["heartbeat"] = heartbeat
        parsed["progress"] = progress
        try:
            token_file.seek(0)
            token_file.truncate()
            json.dump(parsed, token_file, sort_keys=True)
            token_file.write("\n")
            token_file.flush()
        except OSError:
            continue
