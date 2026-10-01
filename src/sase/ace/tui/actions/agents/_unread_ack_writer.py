"""Coalescing ack writer for unread acknowledgments.

Phase ``core-unread-ack-index`` (epic ``sase-1d7``): acks enqueue
``(op_id, keys, identities)`` requests. One worker drains the queue and
issues one ``ack_agent_completions`` Rust call per batch, handing
per-op outcomes back through ``call_from_thread``. Completion removes
the Rust-returned ids from the cached snapshot by id set (no
notifications x keys rescan, no synchronous store read) and schedules
only the guarded async resync.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def remove_cached_notifications_by_ids(app: Any, ids: set[str]) -> int:
    """Drop cached snapshot notifications whose id is in *ids*.

    UI-thread only, no store I/O. Returns the number removed.
    """
    if not ids:
        return 0
    snapshot = getattr(app, "_notification_snapshot_cache", None)
    notifications = getattr(snapshot, "notifications", None)
    if snapshot is None or notifications is None:
        return 0

    from dataclasses import is_dataclass, replace
    from typing import cast

    filtered = [n for n in notifications if getattr(n, "id", None) not in ids]
    if len(filtered) == len(notifications):
        return 0
    removed_count = len(notifications) - len(filtered)

    if isinstance(notifications, list):
        notifications[:] = filtered
        updated_snapshot = snapshot
    elif is_dataclass(snapshot):
        updated_snapshot = replace(cast(Any, snapshot), notifications=filtered)
    else:
        try:
            snapshot.notifications = filtered
        except Exception:
            return 0
        updated_snapshot = snapshot

    set_cache = getattr(app, "_set_notification_snapshot_cache", None)
    if callable(set_cache):
        set_cache(updated_snapshot)
    else:
        try:
            app._notification_snapshot_cache = updated_snapshot
        except (AttributeError, TypeError):
            return 0

    last_unread_ids = getattr(app, "_last_unread_ids", None)
    if isinstance(last_unread_ids, set):
        last_unread_ids.difference_update(ids)
    return removed_count


def _ack_queue_for(app: Any) -> list[Any]:
    """Return the app's ack-write queue, creating it when possible."""
    queue = getattr(app, "_unread_ack_queue", None)
    if isinstance(queue, list):
        return queue
    queue = []
    try:
        app._unread_ack_queue = queue
    except (AttributeError, TypeError):
        pass
    return queue


def enqueue_unread_ack(app: Any, request: Any) -> None:
    """Enqueue *request* and ensure one drain worker is scheduled.

    Must run on the UI thread: it owns the
    ``_unread_ack_write_in_flight`` single-flight flag, so a burst of
    acks coalesces into one batch. Keeps the ``agents`` worker group,
    ``exit_on_error=False``, and teardown cancellation.
    """
    queue = _ack_queue_for(app)
    try:
        queue.append({"request": request})
    except (AttributeError, TypeError):
        return
    if bool(getattr(app, "_unread_ack_write_in_flight", False)):
        return
    try:
        app._unread_ack_write_in_flight = True
    except (AttributeError, TypeError):
        pass

    run_worker = getattr(app, "run_worker", None)
    if not callable(run_worker):
        # No worker host (inline test double): drain on the UI thread.
        # The drain owns the single-flight flag clear (inline or via the
        # host's call_from_thread), including the lost-wakeup reschedule.
        _drain_unread_ack_queue(app)
        return

    def work() -> None:
        _drain_unread_ack_queue(app)

    try:
        run_worker(
            work,
            thread=True,
            name="agents-unread-ack",
            group="agents",
            exit_on_error=False,
        )
    except TypeError:
        try:
            run_worker(work, thread=True)
        except Exception:
            log.exception("Failed to schedule acknowledged-agent notification write")
            _fail_enqueued_requests(app)
    except Exception:
        log.exception("Failed to schedule acknowledged-agent notification write")
        _fail_enqueued_requests(app)


def _fail_enqueued_requests(app: Any) -> None:
    """Restore every queued op when its worker could not be scheduled."""
    queue = getattr(app, "_unread_ack_queue", None)
    if not isinstance(queue, list) or not queue:
        try:
            app._unread_ack_write_in_flight = False
        except (AttributeError, TypeError):
            pass
        return
    try:
        batch = list(queue)
        queue.clear()
    except Exception:
        batch = []
    try:
        app._unread_ack_write_in_flight = False
    except (AttributeError, TypeError):
        pass
    restore = getattr(app, "_restore_unread_notification_dismissal", None)
    if not callable(restore):
        return
    for entry in batch:
        request = entry.get("request") if isinstance(entry, dict) else None
        if request is None:
            continue
        try:
            restore(request)
        except Exception:
            log.exception("Failed to restore unread dismissal after schedule failure")


def _drain_unread_ack_queue(app: Any) -> None:
    """Drain queued acks, one Rust call per batch (worker thread)."""
    while True:
        queue = getattr(app, "_unread_ack_queue", None)
        if not isinstance(queue, list) or not queue:
            break
        try:
            batch = list(queue)
            queue.clear()
        except Exception:
            break
        if not batch:
            break

        seen: set[Any] = set()
        combined_keys: list[Any] = []
        for entry in batch:
            request = entry.get("request") if isinstance(entry, dict) else entry
            for key in getattr(request, "keys", ()) or ():
                if key not in seen:
                    seen.add(key)
                    combined_keys.append(key)
        key_dicts = [
            {"cl_name": cl_name, "raw_suffix": raw_suffix}
            for cl_name, raw_suffix in combined_keys
        ]

        dismissed_ids: set[str] = set()
        generation: int | None = None
        error: Exception | None = None
        try:
            from sase.notifications import ack_agent_completions

            outcome = ack_agent_completions(key_dicts)
            dismissed_ids = set(outcome.dismissed_ids)
            generation = int(outcome.generation)
        except Exception as exc:
            error = exc
            log.exception("Failed to dismiss acknowledged agent notification")
        try:
            from sase.notifications.store import notifications_file_path

            store_bytes: int | None = notifications_file_path().stat().st_size
        except OSError:
            store_bytes = None
        except Exception:
            store_bytes = None

        call_from_thread = getattr(app, "call_from_thread", None)
        if callable(call_from_thread):
            call_from_thread(
                lambda b=batch, i=dismissed_ids, g=generation, e=error, s=store_bytes: (
                    _complete_batch_on_ui(  # noqa: E731
                        app, b, i, g, e, s
                    )
                )
            )
        else:
            _complete_batch_on_ui(
                app, batch, dismissed_ids, generation, error, store_bytes
            )

    _clear_in_flight_when_drained(app)


def _complete_batch_on_ui(
    app: Any,
    batch: list[Any],
    dismissed_ids: set[str],
    generation: int | None,
    error: Exception | None,
    store_bytes: int | None,
) -> None:
    """Apply one batch's outcome to every op on the UI thread.

    Every op completes with the same Rust-returned id set and
    generation, so each op records the generation and the coalesced
    resync count stays as it is today (five rapid acks still complete
    five ops and issue one write). On exception no generation is
    recorded and each op restores only the identities it still owns.
    """
    complete = getattr(app, "_complete_unread_notification_dismissal", None)
    if not callable(complete):
        return
    for entry in batch:
        request = entry.get("request") if isinstance(entry, dict) else entry
        if request is None:
            continue
        try:
            complete(
                request,
                dismissed_count=len(dismissed_ids),
                error=error,
                store_bytes=store_bytes,
                matched_ids=set(dismissed_ids),
                generation=generation,
            )
        except Exception:
            log.exception("Failed to complete acknowledged-agent notification write")


def _clear_in_flight_when_drained(app: Any) -> None:
    """Clear the single-flight flag; reschedule on a lost wakeup."""

    def _clear() -> None:
        try:
            app._unread_ack_write_in_flight = False
        except (AttributeError, TypeError):
            return
        queue = getattr(app, "_unread_ack_queue", None)
        if isinstance(queue, list) and queue:
            _enqueue_unread_ack_reschedule(app)

    call_from_thread = getattr(app, "call_from_thread", None)
    if callable(call_from_thread):
        try:
            call_from_thread(_clear)
        except Exception:
            _clear()
    else:
        _clear()


def _enqueue_unread_ack_reschedule(app: Any) -> None:
    """Reschedule a drain after a lost wakeup (UI thread only)."""
    if bool(getattr(app, "_unread_ack_write_in_flight", False)):
        return
    queue = getattr(app, "_unread_ack_queue", None)
    if not isinstance(queue, list) or not queue:
        return
    try:
        app._unread_ack_write_in_flight = True
    except (AttributeError, TypeError):
        pass
    run_worker = getattr(app, "run_worker", None)
    if not callable(run_worker):
        try:
            _drain_unread_ack_queue(app)
        finally:
            if not callable(getattr(app, "call_from_thread", None)):
                try:
                    app._unread_ack_write_in_flight = False
                except (AttributeError, TypeError):
                    pass
        return

    def work() -> None:
        _drain_unread_ack_queue(app)

    try:
        run_worker(
            work,
            thread=True,
            name="agents-unread-ack",
            group="agents",
            exit_on_error=False,
        )
    except TypeError:
        try:
            run_worker(work, thread=True)
        except Exception:
            log.exception("Failed to reschedule acknowledged-agent notification write")
            _fail_enqueued_requests(app)
    except Exception:
        log.exception("Failed to reschedule acknowledged-agent notification write")
        _fail_enqueued_requests(app)


__all__ = [
    "enqueue_unread_ack",
    "remove_cached_notifications_by_ids",
]
