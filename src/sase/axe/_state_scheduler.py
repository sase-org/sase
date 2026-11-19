"""Legacy flat scheduler state (status, metrics, errors, cycle results).

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so home-directory redirection applies to every reader.
"""

import fcntl
import sase.axe.state as _state  # noqa: I001
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from sase.core.atomic_json import write_json_value_atomic
from sase.core.state_write_guard import best_effort_test_state_write_allowed

_logger = logging.getLogger(__name__)


@dataclass
class AxeStatus:
    """Current status of the axe scheduler for TUI display."""

    pid: int
    started_at: str
    status: Literal["running", "stopped", "error"]
    full_check_interval: int
    hook_interval: int
    max_hook_runners: int
    max_agent_runners: int
    query: str
    zombie_timeout: int
    current_hook_runners: int
    current_agent_runners: int
    last_full_cycle: str | None
    last_hook_cycle: str | None
    next_full_cycle: str | None
    total_patches: int
    filtered_patches: int
    uptime_seconds: int


@dataclass
class CycleResult:
    """Result of a scheduler cycle for logging/debugging."""

    timestamp: str
    cycle_type: Literal["full", "hook", "comment"]
    duration_ms: int
    patches_processed: int
    updates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AxeMetrics:
    """Performance metrics for the axe scheduler."""

    full_cycles_run: int = 0
    hook_cycles_run: int = 0
    total_updates: int = 0
    hooks_started: int = 0
    hooks_completed: int = 0
    mentors_started: int = 0
    mentors_completed: int = 0
    workflows_started: int = 0
    workflows_completed: int = 0
    zombies_detected: int = 0
    stale_running_cleaned: int = 0
    errors_encountered: int = 0


# --- PID File ---


def read_pid_file() -> int | None:
    """Read PID from file.

    Returns:
        PID as integer, or None if file doesn't exist or is invalid.
    """
    pid_file = _state.axe_state_dir() / "pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_pid_file() -> None:
    """Remove PID file on shutdown."""
    pid_file = _state.axe_state_dir() / "pid"
    if not best_effort_test_state_write_allowed(pid_file, category="axe-pid"):
        return
    try:
        pid_file.unlink()
    except OSError:
        pass


# --- Status ---


def read_status() -> AxeStatus | None:
    """Read current status from disk.

    Returns:
        AxeStatus object, or None if file doesn't exist or is invalid.
    """
    status_file = _state.axe_state_dir() / "status.json"
    data = _state.read_json(status_file)
    if data is None:
        return None
    try:
        return AxeStatus(**data)
    except TypeError:
        return None


# --- Cycle Results ---


def write_cycle_result(result: CycleResult) -> None:
    """Write cycle result to disk for debugging.

    Args:
        result: Result of the completed cycle.
    """
    filename = f"last_{result.cycle_type}_cycle.json"
    result_file = _state.axe_state_dir() / filename
    _state.atomic_write_json(result_file, asdict(result))


def read_cycle_result(
    cycle_type: Literal["full", "hook", "comment"],
) -> CycleResult | None:
    """Read last cycle result from disk.

    Args:
        cycle_type: Type of cycle to read ("full", "hook", or "comment").

    Returns:
        CycleResult object, or None if file doesn't exist or is invalid.
    """
    filename = f"last_{cycle_type}_cycle.json"
    result_file = _state.axe_state_dir() / filename
    data = _state.read_json(result_file)
    if data is None:
        return None
    try:
        return CycleResult(**data)
    except TypeError:
        return None


# --- Metrics ---


def read_metrics() -> AxeMetrics | None:
    """Read metrics from disk.

    Returns:
        AxeMetrics object, or None if file doesn't exist or is invalid.
    """
    metrics_file = _state.axe_state_dir() / "metrics.json"
    data = _state.read_json(metrics_file)
    if data is None:
        return None
    try:
        return AxeMetrics(**data)
    except TypeError:
        return None


# --- Errors ---

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
_MAX_PENDING_INCREMENTS = 10_000

#: Fallback signature when the Rust normalizer itself cannot run. The
#: count is what must survive; grouping degrades to one shared bucket.
_UNCLASSIFIED_SIGNATURE = "<unclassified>"

_log_once_guard = threading.Lock()
_logged_kinds: set[str] = set()

_pending_guard = threading.Lock()
_pending_write_failures = 0
_pending_corrupt_files = 0
_pending_increments: list[tuple[str, str, str, str, str]] = []
_pending_overflow = 0


def _log_once(kind: str, message: str, *args: object) -> None:
    """Log once per process per failure kind.

    Args:
        kind: Stable failure kind (for example ``"counter_write"``).
        message: Log message format string.
        args: Format arguments for the message.
    """
    with _log_once_guard:
        if kind in _logged_kinds:
            return
        _logged_kinds.add(kind)
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
        _log_once(kind, "Could not quarantine corrupt %s; starting fresh", target)
        return False
    _log_once(kind, "Moved corrupt %s aside to %s", target, backup.name)
    return True


def _load_counter_locked(counter_file: Path) -> dict:
    """Load the durable counter, quarantining corrupt state.

    Must be called with the error lock held.
    """
    global _pending_corrupt_files
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
            with _pending_guard:
                _pending_corrupt_files += 1
        return _fresh_counter()
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != ERROR_COUNTER_SCHEMA_VERSION
    ):
        if _quarantine_corrupt(counter_file, kind="counter_corrupt"):
            with _pending_guard:
                _pending_corrupt_files += 1
        return _fresh_counter()
    counter = _fresh_counter()
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
    if not counter["interval_start"]:
        counter["interval_start"] = _state.get_timestamp()
    return counter


def _fresh_counter() -> dict:
    """Return a new empty interval counter."""
    return {
        "schema_version": ERROR_COUNTER_SCHEMA_VERSION,
        "interval_start": _state.get_timestamp(),
        "total": 0,
        "write_failures": 0,
        "corrupt_files": 0,
        "groups": {},
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


def _group_key(routine: str, job: str, signature: str) -> str:
    """Return the counter key for one (routine, job, signature) cause."""
    return "\0".join((routine, job, signature))


def _apply_increment(
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


def _load_ring_locked(errors_file: Path) -> list[dict]:
    """Load the sample ring, quarantining corrupt state.

    Must be called with the error lock held.
    """
    global _pending_corrupt_files
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
            with _pending_guard:
                _pending_corrupt_files += 1
        return []
    if not isinstance(errors, list):
        if _quarantine_corrupt(errors_file, kind="ring_corrupt"):
            with _pending_guard:
                _pending_corrupt_files += 1
        return []
    return [entry for entry in errors if isinstance(entry, dict)]


def _ring_signature(entry: dict) -> str:
    """Return the grouping signature of one ring entry."""
    signature = entry.get("failure_signature")
    return signature if isinstance(signature, str) else ""


def _evict_ring_fair(ring: list[dict]) -> None:
    """Bound the ring in place, capping samples per signature.

    Keeps the newest :data:`ERROR_RING_PER_SIGNATURE_CAP` samples of each
    signature so a loud signature can never evict rare ones, then bounds
    the total at :data:`ERROR_RING_CAP` by evicting oldest-first from the
    most-represented signature. In place to keep the caller's list.
    """
    kept_counts: dict[str, int] = {}
    kept_newest_first: list[dict] = []
    for entry in reversed(ring):
        signature = _ring_signature(entry)
        kept = kept_counts.get(signature, 0)
        if kept < ERROR_RING_PER_SIGNATURE_CAP:
            kept_newest_first.append(entry)
            kept_counts[signature] = kept + 1
    ring[:] = kept_newest_first[::-1]
    while len(ring) > ERROR_RING_CAP:
        counts: dict[str, int] = {}
        for entry in ring:
            signature = _ring_signature(entry)
            counts[signature] = counts.get(signature, 0) + 1
        victim_signature = max(counts, key=lambda name: counts[name])
        for index, entry in enumerate(ring):
            if _ring_signature(entry) == victim_signature:
                del ring[index]
                break


def _signature_for_entry(entry: dict) -> str:
    """Return the grouping signature for one error entry.

    An entry's explicit ``failure_signature`` wins; otherwise the
    signature comes from its ``error`` text.
    """
    try:
        from sase.core.axe_error_facade import signature_for_entry
    except Exception:  # noqa: BLE001 - recording must survive facade import faults
        _log_once("signature", "Error-signature facade unavailable; not grouping")
        return _UNCLASSIFIED_SIGNATURE
    try:
        return signature_for_entry(entry)
    except Exception:  # noqa: BLE001 - recording must survive normalizer faults
        _log_once("signature", "Error-signature computation failed; not grouping")
        return _UNCLASSIFIED_SIGNATURE


def append_error(error_info: dict) -> None:
    """Append error to the recent errors ring and the durable counter.

    The durable per-interval counter (``error_counts.json``) is updated
    first under the error lock, so a failed ring write never loses the
    count. The sample ring (``recent_errors.json``) stays bounded at
    :data:`ERROR_RING_CAP` entries with at most
    :data:`ERROR_RING_PER_SIGNATURE_CAP` samples per signature. Failed or
    corrupt writes are counted and logged once instead of dropped.

    Args:
        error_info: Dictionary with error details (timestamp, job, error, traceback).
    """
    global _pending_write_failures, _pending_corrupt_files, _pending_overflow
    errors_file = _state.axe_state_dir() / ERROR_RING_FILENAME
    counter_file = _state.axe_state_dir() / ERROR_COUNTER_FILENAME
    if not best_effort_test_state_write_allowed(errors_file, category="axe-state"):
        return
    if not best_effort_test_state_write_allowed(counter_file, category="axe-state"):
        return
    signature = _signature_for_entry(error_info)
    routine = error_info.get("lumberjack", "")
    job = error_info.get("job", "")
    timestamp = error_info.get("timestamp", "")
    if not isinstance(routine, str):
        routine = str(routine)
    if not isinstance(job, str):
        job = str(job)
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = _state.get_timestamp()
    error_text = error_info.get("error", "")
    sample = error_text if isinstance(error_text, str) else str(error_text)
    stored = dict(error_info)
    stored["failure_signature"] = signature
    stored["timestamp"] = timestamp
    lock_file = errors_file.with_name(f"{errors_file.name}.lock")
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_file, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                counter = _load_counter_locked(counter_file)
                ring = _load_ring_locked(errors_file)
                with _pending_guard:
                    pending_failures = _pending_write_failures
                    pending_corrupt = _pending_corrupt_files
                    pending_increments = list(_pending_increments)
                    pending_overflow = _pending_overflow
                for increment in pending_increments:
                    _apply_increment(
                        counter,
                        routine=increment[0],
                        job=increment[1],
                        signature=increment[2],
                        timestamp=increment[3],
                        sample=increment[4],
                    )
                _apply_increment(
                    counter,
                    routine=routine,
                    job=job,
                    signature=signature,
                    timestamp=timestamp,
                    sample=sample,
                )
                counter["write_failures"] = int(counter.get("write_failures", 0)) + (
                    pending_failures + pending_overflow
                )
                counter["corrupt_files"] = int(counter.get("corrupt_files", 0)) + (
                    pending_corrupt
                )
                try:
                    write_json_value_atomic(counter_file, counter)
                except Exception as exc:  # noqa: BLE001 - every failed write counts
                    with _pending_guard:
                        _pending_write_failures += 1
                        _pending_increments.append(
                            (routine, job, signature, timestamp, sample)
                        )
                        while len(_pending_increments) > _MAX_PENDING_INCREMENTS:
                            _pending_increments.pop(0)
                            _pending_overflow += 1
                    _log_once(
                        "counter_write", "Failed to write %s: %s", counter_file, exc
                    )
                else:
                    with _pending_guard:
                        _pending_write_failures = 0
                        _pending_corrupt_files = 0
                        del _pending_increments[:]
                        _pending_overflow = 0
                ring.append(stored)
                _evict_ring_fair(ring)
                try:
                    write_json_value_atomic(errors_file, ring)
                except Exception as exc:  # noqa: BLE001 - every failed write counts
                    with _pending_guard:
                        _pending_write_failures += 1
                    _log_once("ring_write", "Failed to write %s: %s", errors_file, exc)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except OSError:
        return


def read_errors() -> list[dict]:
    """Read recent errors from disk.

    Returns:
        List of error dictionaries, or empty list if none.
    """
    errors_file = _state.axe_state_dir() / ERROR_RING_FILENAME
    errors = _state.read_json(errors_file)
    if errors is None or not isinstance(errors, list):
        return []
    return errors


def read_error_counts() -> dict | None:
    """Read the durable per-interval error counter from disk.

    Returns:
        Counter dictionary with ``interval_start``, ``total``,
        ``write_failures``, ``corrupt_files``, and per-cause ``groups``;
        or None when the counter file is missing or unreadable. A corrupt
        counter is only moved aside on the ``append_error`` write path,
        never by this read.
    """
    counter_file = _state.axe_state_dir() / ERROR_COUNTER_FILENAME
    try:
        counter = _state.read_json(counter_file)
    except Exception:  # noqa: BLE001 - read path never quarantines
        return None
    if not isinstance(counter, dict):
        return None
    return counter


def write_last_error_digest_ts(ts: str) -> None:
    """Write the timestamp of the newest error in the last digest notification.

    Args:
        ts: ISO formatted timestamp string.
    """
    ts_file = _state.axe_state_dir() / "last_error_digest_ts"
    if not best_effort_test_state_write_allowed(ts_file, category="axe-error-state"):
        return
    ts_file.parent.mkdir(parents=True, exist_ok=True)
    ts_file.write_text(ts)


def read_last_error_digest_ts() -> str | None:
    """Read the high-water mark timestamp from the last error digest.

    Returns:
        ISO timestamp string, or None if file is missing or empty.
    """
    ts_file = _state.axe_state_dir() / "last_error_digest_ts"
    if not ts_file.exists():
        return None
    try:
        content = ts_file.read_text().strip()
        return content if content else None
    except OSError:
        return None


# --- Output Log ---


def read_output_log_tail(lines: int = 1000) -> str:
    """Read the last N lines of the axe output log.

    Args:
        lines: Number of lines to read from the end (default: 1000).

    Returns:
        String containing the last N lines with ANSI codes preserved.
    """
    output_log = _state.axe_output_log_path()
    if not output_log.exists():
        return ""
    return _state.read_tail_seek(output_log, lines)
