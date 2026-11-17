"""Off-thread allocator-trim worker for the idle-time full-GC policy."""

from __future__ import annotations

import threading

from sase.axe.runner_idle_memory import trim_allocator

from ._gc_policy_config import TRIM_THREAD_NAME

_trim_worker_lock = threading.Lock()
_trim_worker_event = threading.Event()
_trim_worker_stop = threading.Event()
_trim_worker: threading.Thread | None = None


def _trim_allocator_quietly() -> None:
    """Run ``trim_allocator`` off the UI thread; never raise."""
    try:
        trim_allocator()
    except Exception:
        pass


def spawn_trim_thread() -> None:
    """Wake the persistent daemon worker to run :func:`_trim_allocator_quietly`.

    ``ctypes`` releases the GIL for the foreign ``malloc_trim`` call, so
    the trim does not freeze the UI. The UI tick only sets an Event; it
    never starts a thread.
    """
    _trim_worker_event.set()


def _trim_worker_main() -> None:
    """Wait for allocator-trim requests until the policy is uninstalled."""
    while not _trim_worker_stop.is_set():
        _trim_worker_event.wait()
        _trim_worker_event.clear()
        if _trim_worker_stop.is_set():
            return
        _trim_allocator_quietly()


def start_trim_worker() -> None:
    """Start the one persistent allocator-trim worker for an installed policy."""
    global _trim_worker
    with _trim_worker_lock:
        if _trim_worker is not None and _trim_worker.is_alive():
            return
        _trim_worker_stop.clear()
        _trim_worker_event.clear()
        worker = threading.Thread(
            target=_trim_worker_main,
            name=TRIM_THREAD_NAME,
            daemon=True,
        )
        _trim_worker = worker
        worker.start()


def stop_trim_worker() -> None:
    """Wake and join the persistent allocator-trim worker at uninstall."""
    global _trim_worker
    with _trim_worker_lock:
        worker = _trim_worker
        if worker is None:
            return
        _trim_worker_stop.set()
        _trim_worker_event.set()
    if worker is not threading.current_thread():
        worker.join()
    with _trim_worker_lock:
        if _trim_worker is worker:
            _trim_worker = None
