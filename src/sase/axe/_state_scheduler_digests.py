"""Scheduler error-interval rotation and digest bookkeeping.

Internal helper module — public API is re-exported through
``sase.axe.state`` (and the ``sase.axe._state_scheduler`` facade).
Do not import from this module directly.

Shared interval state and helpers live in
``sase.axe._state_scheduler_shared`` under public names; the
``_``-prefixed helpers below are used only in this module.
"""

import sase.axe.state as _state  # noqa: I001
import uuid
from datetime import datetime

from sase.axe._state_scheduler_shared import (
    ERROR_COUNTER_FILENAME,
    ERROR_RING_FILENAME,
    bump_write_failures,
    clear_pending_buffers,
    fold_pending_into_counter,
    fresh_error_counter,
    hold_error_lock,
    load_counter_locked,
    load_ring_locked,
    log_once,
    valid_pending_digest,
)
from sase.core.atomic_json import write_json_value_atomic, write_text_atomic
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.core.time import get_timezone, parse_local


def _digest_filename(interval_id: str, interval_end: str) -> str:
    """Return a stable digest filename for one interval."""
    parsed = parse_local(interval_end)
    if parsed is None:
        stamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S")
    else:
        stamp = parsed.strftime("%Y%m%d_%H%M%S")
    return f"digest_{stamp}_{interval_id[:8]}.txt"


def _snapshot_interval(counter: dict, ring: list[dict], *, now: str) -> dict:
    """Copy the current interval into a pending digest record."""
    interval_id = uuid.uuid4().hex
    groups = [
        {
            "routine": group["routine"],
            "job": group["job"],
            "signature": group["signature"],
            "count": int(group["count"]),
            "first_ts": group["first_ts"],
            "last_ts": group["last_ts"],
            "sample": group["sample"],
        }
        for group in sorted(
            counter["groups"].values(),
            key=lambda item: (
                -int(item["count"]),
                item["first_ts"],
                item["routine"],
                item["job"],
                item["signature"],
            ),
        )
    ]
    return {
        "interval_id": interval_id,
        "interval_start": counter["interval_start"],
        "interval_end": now,
        "total": int(counter.get("total") or 0),
        "write_failures": int(counter.get("write_failures") or 0),
        "corrupt_files": int(counter.get("corrupt_files") or 0),
        "samples_kept": len(ring),
        "digest_name": _digest_filename(interval_id, now),
        "groups": groups,
        "ring_samples": [dict(entry) for entry in ring],
    }


def rotate_error_interval() -> list[dict]:
    """Snapshot the current error interval and return unsent digest records.

    Under the error lock, the current counter interval is copied into
    ``pending_digests`` and replaced with a fresh interval starting at now.
    The sample ring is snapshotted into the pending record and then reset so
    the next interval's ``samples_kept`` count is this interval's samples.
    Already-pending records are returned as well so a crash after snapshot
    and before notify re-sends exactly once. An empty interval is not
    snapshotted.
    """
    errors_file = _state.axe_state_dir() / ERROR_RING_FILENAME
    counter_file = _state.axe_state_dir() / ERROR_COUNTER_FILENAME
    if not best_effort_test_state_write_allowed(counter_file, category="axe-state"):
        return []
    reset_ring = best_effort_test_state_write_allowed(errors_file, category="axe-state")
    try:
        with hold_error_lock():
            counter = load_counter_locked(counter_file)
            ring = load_ring_locked(errors_file)
            fold_pending_into_counter(counter)
            pending = [
                dict(item)
                for item in counter.get("pending_digests") or []
                if valid_pending_digest(item)
            ]
            if int(counter.get("total") or 0) <= 0:
                return pending
            now = _state.get_timestamp()
            record = _snapshot_interval(counter, ring, now=now)
            new_counter = fresh_error_counter()
            new_counter["interval_start"] = now
            new_counter["pending_digests"] = pending + [record]
            try:
                write_json_value_atomic(counter_file, new_counter)
            except Exception as exc:  # noqa: BLE001 - keep the unsent snapshot
                log_once("counter_write", "Failed to write %s: %s", counter_file, exc)
                bump_write_failures()
                return pending
            if reset_ring:
                try:
                    write_json_value_atomic(errors_file, [])
                except Exception as exc:  # noqa: BLE001 - snapshot already copied samples
                    log_once("ring_write", "Failed to write %s: %s", errors_file, exc)
                    bump_write_failures()
            clear_pending_buffers()
            return list(new_counter["pending_digests"])
    except OSError:
        return []


def mark_error_digest_sent(interval_id: str) -> None:
    """Drop a pending digest record after it has been notified."""
    if not interval_id:
        return
    counter_file = _state.axe_state_dir() / ERROR_COUNTER_FILENAME
    if not best_effort_test_state_write_allowed(counter_file, category="axe-state"):
        return
    try:
        with hold_error_lock():
            counter = load_counter_locked(counter_file)
            original = [
                item
                for item in counter.get("pending_digests") or []
                if valid_pending_digest(item)
            ]
            remaining = [
                item for item in original if item.get("interval_id") != interval_id
            ]
            if remaining == original:
                return
            counter["pending_digests"] = remaining
            try:
                write_json_value_atomic(counter_file, counter)
            except Exception as exc:  # noqa: BLE001 - retry keeps the pending record
                log_once("counter_write", "Failed to write %s: %s", counter_file, exc)
                bump_write_failures()
    except OSError:
        return


def write_last_error_digest_ts(ts: str) -> None:
    """Write the timestamp of the newest error in the last digest notification.

    Args:
        ts: ISO formatted timestamp string.
    """
    ts_file = _state.axe_state_dir() / "last_error_digest_ts"
    if not best_effort_test_state_write_allowed(ts_file, category="axe-error-state"):
        return
    try:
        write_text_atomic(ts_file, ts)
    except Exception as exc:  # noqa: BLE001 - digest state is best-effort
        log_once("digest_ts_write", "Failed to write %s: %s", ts_file, exc)


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
