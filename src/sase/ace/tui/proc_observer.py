"""Read-only durable proc observer for ACE.

The observer is the one bridge from supervisor-owned durable procs into the
Textual UI. Store reads, session discovery, log tails, and typed-result
decoding happen on a daemon thread; the UI receives immutable snapshots and
completion records through the callback supplied by the app.

This module owns the observer thread itself. The read models it publishes live
in :mod:`._proc_observer_models`, the presentation log in
:mod:`._proc_observer_log`, and the durable-store reads in
:mod:`._proc_observer_store`; all three are re-exported here so callers keep a
single import site.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sase.ace.tui.actions.event_refresh._constants import FULL_SANITY_REFRESH_SECONDS
from sase.ace.tui.actions.event_refresh._surface_tokens import (
    SurfaceToken,
    probe_procs_token,
    surface_token_drifted,
)
from sase.core.state_write_guard import pytest_path_is_sandboxed
from sase.core.time import local_now
from sase.feature_flags import FeatureFlag, current_flags
from sase.procs import Proc, proc_store_path, read_procs

from ._proc_observer_log import ObservedProcLog, ProcLogLine, ProcLogStream
from ._proc_observer_models import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserverSnapshot,
    ProcProjection,
    compose_proc_projection,
    is_monitor_shell_row,
    monitor_row_agent_name,
    proc_projection_for,
    proc_status_is_active,
    recount_projection,
)
from ._proc_observer_store import (
    DETAIL_LOG_LINES,
    ObserverContext,
    ProcWatch,
    decode_completion,
    live_session_ids,
    load_observer_context,
    proc_is_relevant,
    store_proc_row,
)

log = logging.getLogger(__name__)

POLL_SECONDS = 0.5
PROC_OBSERVER_THREAD_NAME = "sase-ace-proc-observer"


@dataclass
class ProcObserver:
    """Daemon-thread read-only projection of durable procs."""

    on_snapshot: Callable[[ProcObserverSnapshot], None]
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _pending: dict[str, ObservedProc] = field(default_factory=dict, init=False)
    _watches: dict[str, ProcWatch] = field(default_factory=dict, init=False)
    _delivered: set[str] = field(default_factory=set, init=False)
    _detail_proc_id: str | None = field(default=None, init=False)
    _context: ObserverContext | None = field(default=None, init=False)
    _last_signature: tuple[Any, ...] | None = field(default=None, init=False)
    _cached_store_rows: list[Proc] | None = field(default=None, init=False, repr=False)
    _last_proc_store_token: SurfaceToken | None = field(
        default=None, init=False, repr=False
    )
    _force_store_read: bool = field(default=True, init=False, repr=False)
    _last_proc_store_sanity_mono: float = field(default=0.0, init=False, repr=False)
    _owner_ref: weakref.ref[Any] | None = field(default=None, init=False, repr=False)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def bind_owner(self, owner: object) -> None:
        """Remember the AceApp (or test double) that owns this observer."""
        self._owner_ref = weakref.ref(owner)

    def start(self) -> None:
        """Start the observer thread."""
        if not pytest_path_is_sandboxed(proc_store_path()):
            return
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            thread = threading.Thread(
                target=self._thread_main,
                name=PROC_OBSERVER_THREAD_NAME,
                daemon=True,
            )
            self._thread = thread
            thread.start()
        _remember_live_observer(self)

    def stop(self, *, timeout: float = 1.0) -> None:
        """Retire the observer thread without touching any proc lifetime."""
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        if thread is not None and thread.is_alive():
            _remember_live_observer(self)
            return
        _forget_live_observer(self)

    def register_pending(
        self,
        *,
        proc_type: str,
        cl_name: str,
        project_file: str,
        display_name: str,
        exclusive_scopes: Collection[str] = (),
        command: Sequence[str] = (),
    ) -> ObservedProc:
        """Add a short-lived local placeholder before the supervisor returns an id."""
        placeholder = ObservedProc(
            proc_id=f"pending-{uuid.uuid4().hex}",
            proc_type=proc_type,
            cl_name=cl_name,
            project_file=project_file,
            status="pending",
            message=f"{display_name} submitted",
            started_at=local_now(),
            display_name=display_name,
            dedup_key=":".join(sorted(exclusive_scopes)) or None,
            exclusive_scopes=frozenset(exclusive_scopes),
            command=list(command) or None,
        )
        with self._lock:
            self._pending[placeholder.proc_id] = placeholder
        self.request_poll()
        return placeholder

    def register_submitted(
        self,
        *,
        placeholder_id: str,
        proc_id: str,
        operation: str,
        result_path: str,
    ) -> None:
        """Watch a supervisor-owned proc and let its store row replace the placeholder."""
        with self._lock:
            pending = self._pending.pop(placeholder_id, None)
            if pending is not None:
                self._pending[placeholder_id] = replace(
                    pending,
                    durable_proc_id=proc_id,
                    status="running",
                    message="Submitted to proc supervisor",
                    store_backed=True,
                )
            self._watches[proc_id] = ProcWatch(
                operation=operation,
                result_path=result_path,
                placeholder_id=placeholder_id,
            )
        self.request_poll()

    def remove_pending(self, placeholder_id: str) -> None:
        with self._lock:
            self._pending.pop(placeholder_id, None)
        self.request_poll()

    def set_detail_proc(self, proc_id: str | None) -> None:
        with self._lock:
            self._detail_proc_id = proc_id

    def request_poll(self) -> None:
        """Ask the observer to publish a fresh snapshot soon."""
        self._last_signature = None
        self._force_store_read = True

    def _thread_main(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            self.poll_once()

    def poll_once(self) -> ProcObserverSnapshot | None:
        """Run one off-thread store read and deliver it if it changed."""
        try:
            snapshot = self._build_snapshot()
        except Exception:
            log.debug("proc observer poll failed", exc_info=True)
            return None
        signature = _snapshot_signature(snapshot)
        if signature == self._last_signature and not snapshot.completions:
            return snapshot
        self._last_signature = signature
        try:
            self.on_snapshot(snapshot)
        except Exception:
            log.debug("proc observer delivery failed", exc_info=True)
        return snapshot

    def _build_snapshot(self) -> ProcObserverSnapshot:
        context = self._resolve_context()
        with self._lock:
            pending = dict(self._pending)
            watches = dict(self._watches)
            delivered = set(self._delivered)
            detail_proc_id = self._detail_proc_id
        rows: list[ObservedProc] = []
        completions: list[ProcCompletionRecord] = []
        session_ids = live_session_ids()
        store_rows = self._store_rows()
        seen_proc_ids: set[str] = set()
        for proc in store_rows:
            if not proc_is_relevant(proc, context=context, watched=watches):
                continue
            seen_proc_ids.add(proc.proc_id)
            rows.append(
                store_proc_row(
                    proc,
                    live_session_ids=session_ids,
                    with_output=proc.proc_id == detail_proc_id,
                )
            )
            if proc.proc_id in watches and not proc_status_is_active(proc.status):
                if proc.proc_id not in delivered:
                    completions.append(decode_completion(proc, watches[proc.proc_id]))

        for placeholder_id, placeholder in pending.items():
            durable_id = placeholder.durable_proc_id
            if durable_id is not None and durable_id in seen_proc_ids:
                continue
            rows.append(placeholder)

        rows.sort(key=lambda row: row.started_at, reverse=True)
        projection = recount_projection(
            ProcProjection(
                rows=tuple(rows),
                session_id=context.session_id,
            )
        )
        if completions:
            with self._lock:
                for completion in completions:
                    self._delivered.add(completion.proc_id)
                    self._pending.pop(
                        watches[completion.proc_id].placeholder_id or "", None
                    )
        return ProcObserverSnapshot(
            projection=projection,
            completions=tuple(completions),
        )

    def _resolve_context(self) -> ObserverContext:
        if self._context is None:
            self._context = load_observer_context()
        return self._context

    def _store_rows(self) -> list[Proc]:
        """Return durable proc rows, skipping an unchanged store parse."""
        force_read = self._force_store_read
        self._force_store_read = False
        if not current_flags().enabled(FeatureFlag.ace_refresh_tokens):
            rows = read_procs()
            self._cached_store_rows = rows
            self._last_proc_store_token = None
            return rows

        token = probe_procs_token(proc_store_path())
        now_mono = time.monotonic()
        sanity_due = (
            now_mono - self._last_proc_store_sanity_mono >= self._proc_sanity_seconds()
        )
        should_read = (
            force_read
            or self._cached_store_rows is None
            or surface_token_drifted(token, self._last_proc_store_token)
            or sanity_due
        )
        cached = self._cached_store_rows
        if should_read or cached is None:
            rows = read_procs()
            self._cached_store_rows = rows
            if not token.indeterminate:
                self._last_proc_store_token = token
            self._last_proc_store_sanity_mono = now_mono
            return rows
        return list(cached)

    def _proc_sanity_seconds(self) -> float:
        owner = self._owner_ref() if self._owner_ref is not None else None
        if owner is not None:
            value = getattr(owner, "sanity_refresh_interval", None)
            if isinstance(value, (int, float)) and float(value) > 0:
                return float(value)
        return FULL_SANITY_REFRESH_SECONDS


def _snapshot_signature(snapshot: ProcObserverSnapshot) -> tuple[Any, ...]:
    return tuple(
        (
            row.proc_id,
            row.durable_proc_id,
            row.status,
            row.message,
            row.phase,
            row.output,
            row.finished_at,
            row.session_live,
            tuple(row.exclusive_scopes),
        )
        for row in snapshot.projection.rows
    )


_LIVE_OBSERVERS: dict[int, weakref.ref[ProcObserver]] = {}
_LIVE_OBSERVERS_LOCK = threading.Lock()


def _remember_live_observer(observer: ProcObserver) -> None:
    ident = id(observer)

    def _drop(_ref: weakref.ref[ProcObserver], *, key: int = ident) -> None:
        with _LIVE_OBSERVERS_LOCK:
            _LIVE_OBSERVERS.pop(key, None)

    with _LIVE_OBSERVERS_LOCK:
        _LIVE_OBSERVERS[ident] = weakref.ref(observer, _drop)


def _forget_live_observer(observer: ProcObserver) -> None:
    with _LIVE_OBSERVERS_LOCK:
        _LIVE_OBSERVERS.pop(id(observer), None)


def _live_observers() -> list[ProcObserver]:
    with _LIVE_OBSERVERS_LOCK:
        live: list[ProcObserver] = []
        stale: list[int] = []
        for ident, ref in _LIVE_OBSERVERS.items():
            observer = ref()
            if observer is None:
                stale.append(ident)
                continue
            live.append(observer)
        for ident in stale:
            _LIVE_OBSERVERS.pop(ident, None)
        return live


def stop_orphaned_proc_observers(*, timeout: float = 1.0) -> None:
    """Stop started observers that are not the current observer of a running app.

    ACE tests often construct :class:`~sase.ace.tui.app.AceApp` without mounting
    it, which starts ``sase-ace-proc-observer`` in ``__init__``. Those threads
    keep calling ``load_merged_config()`` via timezone conversion and poison
    later config-cache tests on the same process. Shared :class:`AcePageGroup`
    apps stay ``is_running`` between checkouts, so their current observer is
    left alone.
    """
    protected: set[int] = set()
    observers = _live_observers()
    for observer in observers:
        owner = observer._owner_ref() if observer._owner_ref is not None else None
        if owner is None or not getattr(owner, "is_running", False):
            continue
        if getattr(owner, "_proc_observer", None) is observer:
            protected.add(id(observer))
    for observer in observers:
        if id(observer) in protected:
            continue
        observer.stop(timeout=timeout)


__all__ = [
    "DETAIL_LOG_LINES",
    "POLL_SECONDS",
    "PROC_OBSERVER_THREAD_NAME",
    "ObservedProc",
    "ObservedProcLog",
    "ObserverContext",
    "ProcCompletionRecord",
    "ProcLogLine",
    "ProcLogStream",
    "ProcObserver",
    "ProcObserverSnapshot",
    "ProcProjection",
    "ProcWatch",
    "compose_proc_projection",
    "is_monitor_shell_row",
    "monitor_row_agent_name",
    "proc_projection_for",
    "store_proc_row",
]
