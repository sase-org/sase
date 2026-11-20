"""Shared error-interval state for scheduler error accounting.

Internal helper module — public API is re-exported through
``sase.axe.state`` (and the ``sase.axe._state_scheduler`` facade).
Do not import from this module directly.

The shared names here are public (no ``_`` prefix) so the sibling
section modules ``sase.axe._state_scheduler_errors`` and
``sase.axe._state_scheduler_digests`` can share them without importing
a private name across modules. Helpers used only in this module keep
their ``_``-prefixed names. Paths and shared helpers are looked up
through ``sase.axe.state`` at call time so home-directory redirection
applies to every reader.
"""

import fcntl
import sase.axe.state as _state  # noqa: I001
import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_logger = logging.getLogger(__name__)

#: Schema version of the durable per-interval error counter.
ERROR_COUNTER_SCHEMA_VERSION = 1

#: Counter file holding exact per-interval, per-cause error totals.
ERROR_COUNTER_FILENAME = "error_counts.json"

#: Sample ring file holding the most recent error entries.
ERROR_RING_FILENAME = "recent_errors.json"

#: Upper bound on ring entries; the ring stays bounded at this size.
ERROR_RING_CAP = 100

#: Upper bound on ring entries kept per signature, so a loud signature can
#: no longer evict rare ones.
ERROR_RING_PER_SIGNATURE_CAP = 5

#: Upper bound on the sample text kept per counter group, in characters.
ERROR_GROUP_SAMPLE_CHARS = 2000

#: Upper bound on queued increments kept in process while counter writes
#: fail; beyond it the lost increments fold into ``write_failures``.
MAX_PENDING_INCREMENTS = 10_000

#: Fallback signature when the Rust normalizer itself cannot run. The
#: count is what must survive; grouping degrades to one shared bucket.
UNCLASSIFIED_SIGNATURE = "<unclassified>"

log_once_guard = threading.Lock()
logged_kinds: set[str] = set()

pending_guard = threading.Lock()
pending_write_failures = 0
pending_corrupt_files = 0
pending_increments: list[tuple[str, str, str, str, str]] = []
pending_overflow = 0


def log_once(kind: str, message: str, *args: object) -> None:
    """Log once per process per failure kind.

    Args:
        kind: Stable failure kind (for example ``"counter_write"``).
        message: Log message format string.
        args: Format arguments for the message.
    """
    with log_once_guard:
        if kind in logged_kinds:
            return
        logged_kinds.add(kind)
    _logger.warning(message, *args)


def _quarantine_corrupt(path: Path, *, kind: str) -> bool:
    """Move a corrupt state file aside instead of resetting it silently.

    Args:
        path: Corrupt file to preserve.
        kind: Failure kind for once-per-process logging.

    Returns:
        True when the file existed and was moved aside.
    """
    target = path
    try:
        if not target.exists():
            return False
    except OSError:
        return False
    suffix = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    backup = target.with_name(f"{target.name}.corrupt-{suffix}-pid{os.getpid()}")
    try:
        os.replace(target, backup)
    except OSError:
        log_once(kind, "Could not quarantine corrupt %s; starting fresh", target)
        return False
    log_once(kind, "Moved corrupt %s aside to %s", target, backup.name)
    return True


def load_counter_locked(counter_file: Path) -> dict:
    """Load the durable counter, quarantining corrupt state.

    Must be called with the error lock held.
    """
    global pending_corrupt_files
    try:
        raw = _state.read_json(counter_file)
    except Exception:  # noqa: BLE001 - a corrupt counter must not lose the count
        raw = None
    if raw is None:
        try:
            exists = counter_file.exists()
        except OSError:
            exists = False
        if exists and _quarantine_corrupt(counter_file, kind="counter_corrupt"):
            with pending_guard:
                pending_corrupt_files += 1
        return fresh_error_counter()
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != ERROR_COUNTER_SCHEMA_VERSION
    ):
        if _quarantine_corrupt(counter_file, kind="counter_corrupt"):
            with pending_guard:
                pending_corrupt_files += 1
        return fresh_error_counter()
    counter = fresh_error_counter()
    for key in ("interval_start", "total", "write_failures", "corrupt_files"):
        value = raw.get(key)
        if isinstance(value, int) and value >= 0:
            counter[key] = value
        elif key == "interval_start" and isinstance(value, str) and value:
            counter[key] = value
    groups = raw.get("groups")
    if isinstance(groups, dict):
        for key, group in groups.items():
            if isinstance(key, str) and _valid_group(group):
                counter["groups"][key] = {
                    "routine": group["routine"],
                    "job": group["job"],
                    "signature": group["signature"],
                    "count": group["count"],
                    "first_ts": group["first_ts"],
                    "last_ts": group["last_ts"],
                    "sample": group["sample"],
                }
    pending = raw.get("pending_digests")
    if isinstance(pending, list):
        counter["pending_digests"] = [
            dict(item) for item in pending if valid_pending_digest(item)
        ]
    if not counter["interval_start"]:
        counter["interval_start"] = _state.get_timestamp()
    return counter


def fresh_error_counter() -> dict:
    """Return a new empty interval counter."""
    return {
        "schema_version": ERROR_COUNTER_SCHEMA_VERSION,
        "interval_start": _state.get_timestamp(),
        "total": 0,
        "write_failures": 0,
        "corrupt_files": 0,
        "groups": {},
        "pending_digests": [],
    }


def _valid_group(group: object) -> bool:
    """Return whether a counter group record has the expected shape."""
    if not isinstance(group, dict):
        return False
    for key in ("routine", "job", "signature", "first_ts", "last_ts", "sample"):
        if not isinstance(group.get(key), str):
            return False
    count = group.get("count")
    return isinstance(count, int) and count > 0


def valid_pending_digest(record: object) -> bool:
    """Return whether a pending digest record has the expected shape."""
    if not isinstance(record, dict):
        return False
    for key in ("interval_id", "interval_start", "interval_end"):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            return False
    total = record.get("total")
    groups = record.get("groups")
    return isinstance(total, int) and total >= 0 and isinstance(groups, list)


@contextmanager
def hold_error_lock() -> Iterator[None]:
    """Hold the exclusive lock used by the error ring and interval counter."""
    errors_file = _state.axe_state_dir() / ERROR_RING_FILENAME
    lock_file = errors_file.with_name(f"{errors_file.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def fold_pending_into_counter(counter: dict) -> None:
    """Fold in-process pending increments and failure counts into *counter*."""
    with pending_guard:
        pending_failures = pending_write_failures
        pending_corrupt = pending_corrupt_files
        increments = list(pending_increments)
        overflow = pending_overflow
    for increment in increments:
        apply_error_increment(
            counter,
            routine=increment[0],
            job=increment[1],
            signature=increment[2],
            timestamp=increment[3],
            sample=increment[4],
        )
    counter["write_failures"] = int(counter.get("write_failures", 0)) + (
        pending_failures + overflow
    )
    counter["corrupt_files"] = int(counter.get("corrupt_files", 0)) + pending_corrupt


def clear_pending_buffers() -> None:
    """Clear in-process error-accounting buffers after a successful write."""
    global pending_write_failures, pending_corrupt_files, pending_overflow
    with pending_guard:
        pending_write_failures = 0
        pending_corrupt_files = 0
        del pending_increments[:]
        pending_overflow = 0


def bump_write_failures() -> None:
    """Count one in-process write failure."""
    global pending_write_failures
    with pending_guard:
        pending_write_failures += 1


def record_counter_write_failure(
    routine: str, job: str, signature: str, timestamp: str, sample: str
) -> None:
    """Count one failed counter write and queue its increment for retry.

    The queued increment is folded back into the counter by
    :func:`fold_pending_into_counter` on the next successful write; when
    the queue is full the oldest increment is dropped and the loss folds
    into ``write_failures`` instead.
    """
    global pending_write_failures, pending_overflow
    with pending_guard:
        pending_write_failures += 1
        pending_increments.append((routine, job, signature, timestamp, sample))
        while len(pending_increments) > MAX_PENDING_INCREMENTS:
            pending_increments.pop(0)
            pending_overflow += 1


def _group_key(routine: str, job: str, signature: str) -> str:
    """Return the counter key for one (routine, job, signature) cause."""
    return "\0".join((routine, job, signature))


def apply_error_increment(
    counter: dict,
    *,
    routine: str,
    job: str,
    signature: str,
    timestamp: str,
    sample: str,
) -> None:
    """Fold one error into the interval counter in place."""
    counter["total"] = int(counter.get("total", 0)) + 1
    key = _group_key(routine, job, signature)
    groups = counter["groups"]
    group = groups.get(key)
    if group is None:
        groups[key] = {
            "routine": routine,
            "job": job,
            "signature": signature,
            "count": 1,
            "first_ts": timestamp,
            "last_ts": timestamp,
            "sample": sample[:ERROR_GROUP_SAMPLE_CHARS],
        }
        return
    group["count"] += 1
    if timestamp < group["first_ts"]:
        group["first_ts"] = timestamp
    if timestamp > group["last_ts"]:
        group["last_ts"] = timestamp


def load_ring_locked(errors_file: Path) -> list[dict]:
    """Load the sample ring, quarantining corrupt state.

    Must be called with the error lock held.
    """
    global pending_corrupt_files
    errors: object = None
    try:
        errors = _state.read_json(errors_file)
    except Exception:  # noqa: BLE001 - a corrupt ring must not lose the count
        errors = None
    if errors is None:
        try:
            exists = errors_file.exists()
        except OSError:
            exists = False
        if exists and _quarantine_corrupt(errors_file, kind="ring_corrupt"):
            with pending_guard:
                pending_corrupt_files += 1
        return []
    if not isinstance(errors, list):
        if _quarantine_corrupt(errors_file, kind="ring_corrupt"):
            with pending_guard:
                pending_corrupt_files += 1
        return []
    return [entry for entry in errors if isinstance(entry, dict)]
