"""Scheduler error ring and durable per-interval counter.

Internal helper module — public API is re-exported through
``sase.axe.state`` (and the ``sase.axe._state_scheduler`` facade).
Do not import from this module directly.

Shared interval state and helpers live in
``sase.axe._state_scheduler_shared`` under public names; the
``_``-prefixed helpers below are used only in this module.
"""

import sase.axe.state as _state  # noqa: I001
from sase.axe._state_scheduler_shared import (
    ERROR_COUNTER_FILENAME,
    ERROR_RING_CAP,
    ERROR_RING_FILENAME,
    ERROR_RING_PER_SIGNATURE_CAP,
    UNCLASSIFIED_SIGNATURE,
    apply_error_increment,
    bump_write_failures,
    clear_pending_buffers,
    fold_pending_into_counter,
    hold_error_lock,
    load_counter_locked,
    load_ring_locked,
    log_once,
    record_counter_write_failure,
)
from sase.core.atomic_json import write_json_value_atomic
from sase.core.state_write_guard import best_effort_test_state_write_allowed


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
        log_once("signature", "Error-signature facade unavailable; not grouping")
        return UNCLASSIFIED_SIGNATURE
    try:
        return signature_for_entry(entry)
    except Exception:  # noqa: BLE001 - recording must survive normalizer faults
        log_once("signature", "Error-signature computation failed; not grouping")
        return UNCLASSIFIED_SIGNATURE


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
    try:
        with hold_error_lock():
            counter = load_counter_locked(counter_file)
            ring = load_ring_locked(errors_file)
            fold_pending_into_counter(counter)
            apply_error_increment(
                counter,
                routine=routine,
                job=job,
                signature=signature,
                timestamp=timestamp,
                sample=sample,
            )
            try:
                write_json_value_atomic(counter_file, counter)
            except Exception as exc:  # noqa: BLE001 - every failed write counts
                record_counter_write_failure(routine, job, signature, timestamp, sample)
                log_once("counter_write", "Failed to write %s: %s", counter_file, exc)
            else:
                clear_pending_buffers()
            ring.append(stored)
            _evict_ring_fair(ring)
            try:
                write_json_value_atomic(errors_file, ring)
            except Exception as exc:  # noqa: BLE001 - every failed write counts
                bump_write_failures()
                log_once("ring_write", "Failed to write %s: %s", errors_file, exc)
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
