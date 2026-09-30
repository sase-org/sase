"""Coalescing ack writer for unread acknowledgments.

Phase ``ack-pipeline`` (epic ``sase-1d7``): acks enqueue ``(op_id, keys,
identities)`` plus a shallow copy of the cached snapshot's notification
list. One worker drains the queue and issues one
``dismiss_agent_completion_notifications_matching_agents`` call per batch,
handing per-op outcomes back through ``call_from_thread``. Completion
removes the worker-computed matching ids from the cached snapshot by id
set (no notifications x keys rescan, no synchronous store read) and
schedules only the guarded async resync.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _matching_notification_ids_for_keys(
    notifications: Any,
    keys: Any,
) -> set[str]:
    """Return cached-snapshot ids matching any of *keys*.

    Pure in-memory scan safe to run on the worker thread: no store I/O.
    Uses the single completion-or-settlement predicate so the removal set
    matches what the Rust dismiss call owns.
    """
    try:
        key_list = list(keys or ())
    except TypeError:
        return set()
    if not key_list:
        return set()
    try:
        notif_list = list(notifications or [])
    except TypeError:
        return set()
    if not notif_list:
        return set()

    from ._notification_utils import agent_row_notification_matches_agent

    matched: set[str] = set()
    for notification in notif_list:
        notification_id = getattr(notification, "id", None)
        if not isinstance(notification_id, str):
            continue
        for cl_name, raw_suffix in key_list:
            try:
                if agent_row_notification_matches_agent(
                    notification,
                    cl_name=cl_name,
                    raw_suffix=raw_suffix,
                ):
                    matched.add(notification_id)
                    break
            except Exception:
                continue
    return matched


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


def _snapshot_notification_copy(app: Any) -> list[Any]:
    """Return a shallow copy of the cached notification list (UI thread)."""
    snapshot = getattr(app, "_notification_snapshot_cache", None)
    try:
        notifications = getattr(snapshot, "notifications", None)
    except Exception:
        return []
    if not notifications:
        return []
    try:
        return list(notifications)
    except TypeError:
        return []


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

    Must run on the UI thread: it captures the cached snapshot list and
    owns the ``_unread_ack_write_in_flight`` single-flight flag, so a
    burst of acks coalesces into one batch. Keeps the ``agents`` worker
    group, ``exit_on_error=False``, and teardown cancellation.
    """
    queue = _ack_queue_for(app)
    try:
        queue.append(
            {
                "request": request,
                "snapshot_notifications": _snapshot_notification_copy(app),
            }
        )
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

        per_op_ids: list[set[str]] = []
        for entry in batch:
            if isinstance(entry, dict):
                request = entry.get("request")
                snap_notifications = entry.get("snapshot_notifications", [])
            else:
                request = entry
                snap_notifications = []
            keys = getattr(request, "keys", ()) or ()
            try:
                per_op_ids.append(
                    _matching_notification_ids_for_keys(snap_notifications, keys)
                )
            except Exception:
                per_op_ids.append(set())

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

        dismissed_count = 0
        error: Exception | None = None
        try:
            if key_dicts:
                from sase.notifications import (
                    dismiss_agent_completion_notifications_matching_agents,
                )

                dismissed_count = (
                    dismiss_agent_completion_notifications_matching_agents(key_dicts)
                )
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
                lambda b=batch, p=per_op_ids, d=dismissed_count, e=error, s=store_bytes: (
                    _complete_batch_on_ui(  # noqa: E731
                        app, b, p, d, e, s
                    )
                )
            )
        else:
            _complete_batch_on_ui(
                app, batch, per_op_ids, dismissed_count, error, store_bytes
            )

    _clear_in_flight_when_drained(app)


def _complete_batch_on_ui(
    app: Any,
    batch: list[Any],
    per_op_ids: list[set[str]],
    dismissed_count: int,
    error: Exception | None,
    store_bytes: int | None,
) -> None:
    """Apply one batch's per-op outcomes on the UI thread."""
    complete = getattr(app, "_complete_unread_notification_dismissal", None)
    if not callable(complete):
        return
    for entry, matched_ids in zip(batch, per_op_ids, strict=False):
        request = entry.get("request") if isinstance(entry, dict) else entry
        if request is None:
            continue
        try:
            complete(
                request,
                dismissed_count=dismissed_count,
                error=error,
                store_bytes=store_bytes,
                matched_ids=matched_ids,
            )
        except TypeError:
            # Older test doubles override the pre-pipeline signature.
            complete(
                request,
                dismissed_count=dismissed_count,
                error=error,
                store_bytes=store_bytes,
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
