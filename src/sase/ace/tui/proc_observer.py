"""Read-only durable proc observer for ACE.

The observer is the one bridge from supervisor-owned durable procs into the
Textual UI. Store reads, session discovery, log tails, and typed-result
decoding happen on a daemon thread; the UI receives immutable snapshots and
completion records through the callback supplied by the app.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.core.state_write_guard import pytest_path_is_sandboxed
from sase.core.time import local_now, to_local
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult, OperationIOError, read_operation_result
from sase.procs import (
    ACTIVE_PROC_STATUSES,
    Proc,
    proc_store_path,
    read_proc_log_tail,
    read_procs,
)
from sase.procs.runtime import proc_operation_result_path
from sase.project_display_names import humanize_cl_name

log = logging.getLogger(__name__)

ProcLogStream = Literal["stdout", "stderr", "progress", "header", "result"]

POLL_SECONDS = 0.5
DETAIL_LOG_LINES = 400
_MAX_PROC_LOG_LINES = 5_000
_MAX_PROC_LOG_CHARS = 512 * 1024
_ACTIVE_STATUSES = frozenset(ACTIVE_PROC_STATUSES)


@dataclass(frozen=True)
class ProcLogLine:
    """One append-only presentation log line."""

    text: str
    stream: ProcLogStream
    ts: datetime


@dataclass(frozen=True)
class _ProcLogSnapshot:
    """Immutable view of a presentation log."""

    lines: tuple[ProcLogLine, ...]
    version: int
    trimmed_count: int


@dataclass
class _ObservedProcLog:
    """Thread-safe, bounded log used only for ACE-local presentation rows."""

    max_lines: int = _MAX_PROC_LOG_LINES
    max_chars: int = _MAX_PROC_LOG_CHARS
    _lines: list[ProcLogLine] = field(default_factory=list, init=False, repr=False)
    _chars: int = field(default=0, init=False, repr=False)
    _trimmed_count: int = field(default=0, init=False, repr=False)
    _version: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def append(self, text: str, *, stream: ProcLogStream = "stdout") -> None:
        """Append text to the log, splitting multi-line chunks into log lines."""
        if text == "":
            return
        entries = text.splitlines() or [text]
        with self._lock:
            for entry in entries:
                self._lines.append(
                    ProcLogLine(text=entry.rstrip("\r"), stream=stream, ts=local_now())
                )
                self._chars += len(entry)
            while self._lines and (
                len(self._lines) > self.max_lines or self._chars > self.max_chars
            ):
                removed = self._lines.pop(0)
                self._chars -= len(removed.text)
                self._trimmed_count += 1
            self._version += 1

    def snapshot(self) -> _ProcLogSnapshot:
        with self._lock:
            return _ProcLogSnapshot(
                lines=tuple(self._lines),
                version=self._version,
                trimmed_count=self._trimmed_count,
            )

    def text(self) -> str:
        snapshot = self.snapshot()
        lines: list[str] = []
        if snapshot.trimmed_count:
            lines.append(f"... {snapshot.trimmed_count} earlier lines trimmed")
        lines.extend(line.text for line in snapshot.lines)
        if not lines:
            return ""
        return "\n".join(lines) + "\n"


@dataclass
class ObservedProc:
    """Read-only presentation state for one proc row."""

    proc_id: str
    proc_type: str
    cl_name: str
    project_file: str
    status: str
    message: str
    started_at: datetime
    display_name: str | None = None
    dedup_key: str | None = None
    exclusive_scopes: frozenset[str] = frozenset()
    finished_at: datetime | None = None
    output: str = ""
    error: str | None = None
    log: _ObservedProcLog = field(default_factory=_ObservedProcLog)
    command: list[str] | None = None
    phase: str | None = None
    exit_code: int | None = None
    durable_proc_id: str | None = None
    store_backed: bool = False
    session_id: str | None = None
    session_label: str | None = None
    session_live: bool = True
    origin: str = ""

    @property
    def label(self) -> str:
        """Return the user-facing proc label."""
        if self.display_name:
            return self.display_name
        if self.cl_name:
            return f"{self.proc_type} {humanize_cl_name(self.cl_name)}"
        return self.proc_type

    def get_live_output(self) -> str:
        """Return retained presentation log output or durable log text."""
        log_text = self.log.text()
        if log_text:
            return log_text
        return self.output


@dataclass(frozen=True)
class ProcProjection:
    """UI-side read model for observed procs."""

    rows: tuple[ObservedProc, ...] = ()
    active_count: int = 0
    active_monitor_count: int = 0
    session_id: str | None = None

    def scoped_rows(self, *, all_sessions: bool) -> list[ObservedProc]:
        """Return rows for the Procs pane's current scope."""
        if all_sessions:
            return list(self.rows)
        return [
            row
            for row in self.rows
            if row.session_id is None
            or row.session_id == self.session_id
            or not row.session_live
        ]

    def active_rows(self, *, all_sessions: bool = False) -> list[ObservedProc]:
        """Return active rows whose session owner can still be live."""
        return [
            row
            for row in self.scoped_rows(all_sessions=all_sessions)
            if row.status in _ACTIVE_STATUSES
            and (row.session_id is None or row.session_live)
        ]

    def active_monitor_rows(self, *, all_sessions: bool = False) -> list[ObservedProc]:
        """Return active rows that are ``sase monitor start`` proc shells."""
        return [
            row
            for row in self.active_rows(all_sessions=all_sessions)
            if is_monitor_shell_row(row)
        ]

    def scope_conflict(self, exclusive_scopes: Collection[str]) -> ObservedProc | None:
        """Return the active row claiming any requested exclusive scope."""
        requested = frozenset(exclusive_scopes)
        if not requested:
            return None
        for row in self.rows:
            if row.status in _ACTIVE_STATUSES and requested & row.exclusive_scopes:
                return row
        return None


def compose_proc_projection(
    durable: ProcProjection,
    session_rows: Sequence[ObservedProc] = (),
) -> ProcProjection:
    """Combine the durable observer snapshot with live session-local rows."""
    if not session_rows:
        return durable
    seen = {row.proc_id for row in durable.rows}
    extra: list[ObservedProc] = []
    for row in session_rows:
        if row.proc_id in seen:
            continue
        extra.append(_attribute_session_row(row, durable.session_id))
        seen.add(row.proc_id)
    if not extra:
        return durable
    rows = [*durable.rows, *extra]
    rows.sort(key=lambda item: item.started_at, reverse=True)
    projection = ProcProjection(
        rows=tuple(rows),
        session_id=durable.session_id,
    )
    return replace(
        projection,
        active_count=len(projection.active_rows()),
        active_monitor_count=len(projection.active_monitor_rows()),
    )


def proc_projection_for(app: Any) -> ProcProjection:
    """Return the UI-effective proc projection for *app*."""
    compose = getattr(app, "_effective_proc_projection", None)
    if callable(compose):
        projection = compose()
        if isinstance(projection, ProcProjection):
            return projection
    projection = getattr(app, "_proc_projection", None)
    return projection if isinstance(projection, ProcProjection) else ProcProjection()


def _attribute_session_row(row: ObservedProc, session_id: str | None) -> ObservedProc:
    if row.session_id == session_id:
        return row
    return replace(row, session_id=session_id, session_live=True)


@dataclass(frozen=True)
class ProcCompletionRecord:
    """One terminal typed completion decoded by the observer thread."""

    proc_id: str
    operation: str
    result: DurableOperationResult | None
    error: str | None = None


@dataclass(frozen=True)
class ProcObserverSnapshot:
    """Immutable observer-to-UI delivery record."""

    projection: ProcProjection
    completions: tuple[ProcCompletionRecord, ...] = ()


@dataclass(frozen=True)
class _Watch:
    operation: str
    result_path: str
    placeholder_id: str | None = None


@dataclass(frozen=True)
class _ObserverContext:
    session_id: str | None
    session_label: str | None
    project: str | None
    workspace_num: int | None
    cwd: str


@dataclass
class ProcObserver:
    """Daemon-thread read-only projection of durable procs."""

    on_snapshot: Callable[[ProcObserverSnapshot], None]
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _pending: dict[str, ObservedProc] = field(default_factory=dict, init=False)
    _watches: dict[str, _Watch] = field(default_factory=dict, init=False)
    _delivered: set[str] = field(default_factory=set, init=False)
    _detail_proc_id: str | None = field(default=None, init=False)
    _context: _ObserverContext | None = field(default=None, init=False)
    _last_signature: tuple[Any, ...] | None = field(default=None, init=False)

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

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
                name="sase-ace-proc-observer",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self, *, timeout: float = 1.0) -> None:
        """Retire the observer thread without touching any proc lifetime."""
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

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
            self._watches[proc_id] = _Watch(
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
        live_session_ids = _live_session_ids()
        store_rows = read_procs()
        seen_proc_ids: set[str] = set()
        for proc in store_rows:
            if not _is_relevant(proc, context=context, watched=watches):
                continue
            seen_proc_ids.add(proc.proc_id)
            rows.append(
                _store_proc_row(
                    proc,
                    live_session_ids=live_session_ids,
                    with_output=proc.proc_id == detail_proc_id,
                )
            )
            if proc.proc_id in watches and proc.status not in _ACTIVE_STATUSES:
                if proc.proc_id not in delivered:
                    completions.append(_decode_completion(proc, watches[proc.proc_id]))

        for placeholder_id, placeholder in pending.items():
            durable_id = placeholder.durable_proc_id
            if durable_id is not None and durable_id in seen_proc_ids:
                continue
            rows.append(placeholder)

        rows.sort(key=lambda row: row.started_at, reverse=True)
        projection = ProcProjection(
            rows=tuple(rows),
            session_id=context.session_id,
        )
        projection = replace(
            projection,
            active_count=len(projection.active_rows()),
            active_monitor_count=len(projection.active_monitor_rows()),
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

    def _resolve_context(self) -> _ObserverContext:
        if self._context is None:
            self._context = _load_context()
        return self._context


def is_monitor_shell_row(row: ObservedProc) -> bool:
    """Return whether an observed row is a ``sase monitor start`` proc shell."""
    return row.origin == MONITOR_PROC_ORIGIN


def _store_proc_row(
    proc: Proc,
    *,
    live_session_ids: frozenset[str] = frozenset(),
    with_output: bool = False,
) -> ObservedProc:
    """Adapt one durable proc row into an observed row."""
    started_at = _local_datetime(proc.started_at or proc.created_at) or local_now()
    output = _read_log_tail(proc.proc_id) if with_output else ""
    return ObservedProc(
        proc_id=proc.proc_id,
        proc_type=proc.kind,
        cl_name=proc.cl_name or "",
        project_file="",
        status=proc.status,
        message=proc.message or "",
        started_at=started_at,
        display_name=proc.label,
        finished_at=_local_datetime(proc.finished_at),
        output=output,
        error=proc.message if proc.status in {"error", "killed"} else None,
        command=list(proc.command) or None,
        phase=proc.phase,
        exit_code=proc.exit_code,
        durable_proc_id=proc.proc_id,
        store_backed=True,
        session_id=proc.session_id,
        session_label=proc.session_label,
        session_live=bool(proc.session_id and proc.session_id in live_session_ids),
        exclusive_scopes=frozenset(proc.concurrency_keys),
        origin=proc.origin,
    )


def _decode_completion(proc: Proc, watch: _Watch) -> ProcCompletionRecord:
    raw_result_path = watch.result_path
    if not raw_result_path and isinstance(proc.result, Mapping):
        value = proc.result.get("result_path")
        raw_result_path = value if isinstance(value, str) else ""
    if not raw_result_path:
        raw_result_path = str(proc_operation_result_path(proc.proc_id))
    try:
        result = read_operation_result(
            raw_result_path,
            expected_operation=watch.operation,
            expected_proc_id=proc.proc_id,
        )
    except OperationIOError as exc:
        return ProcCompletionRecord(
            proc_id=proc.proc_id,
            operation=watch.operation,
            result=None,
            error=str(exc),
        )
    return ProcCompletionRecord(
        proc_id=proc.proc_id,
        operation=watch.operation,
        result=result,
    )


def _is_relevant(
    proc: Proc,
    *,
    context: _ObserverContext,
    watched: Mapping[str, _Watch],
) -> bool:
    if proc.proc_id in watched:
        return True
    if proc.session_id is None:
        return True
    if context.session_id is not None and proc.session_id == context.session_id:
        return True
    if proc.origin == "ace":
        return True
    if context.project is not None and proc.project == context.project:
        return True
    if "ace" in proc.tags:
        return True
    return False


def _load_context() -> _ObserverContext:
    """Resolve this process's session attribution on the observer thread."""
    from sase.sessions import current_session_id, live_sessions, session_display_label

    try:
        session_id: str | None = current_session_id()
    except Exception:
        session_id = None
    identity = None
    if session_id is not None:
        try:
            identity = next(
                (item for item in live_sessions() if item.session_id == session_id),
                None,
            )
        except Exception:
            identity = None
    if identity is None:
        return _ObserverContext(
            session_id=session_id,
            session_label=None,
            project=None,
            workspace_num=None,
            cwd=os.getcwd(),
        )
    return _ObserverContext(
        session_id=identity.session_id,
        session_label=session_display_label(identity),
        project=identity.project,
        workspace_num=identity.workspace_num,
        cwd=identity.cwd or os.getcwd(),
    )


def _live_session_ids() -> frozenset[str]:
    try:
        from sase.sessions import live_sessions

        return frozenset(identity.session_id for identity in live_sessions())
    except Exception:
        return frozenset()


def _read_log_tail(proc_id: str) -> str:
    try:
        return read_proc_log_tail(proc_id, DETAIL_LOG_LINES)
    except (OSError, ValueError):
        return ""


def _local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return to_local(parsed)


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


__all__ = [
    "DETAIL_LOG_LINES",
    "POLL_SECONDS",
    "ObservedProc",
    "ProcCompletionRecord",
    "ProcLogLine",
    "ProcLogStream",
    "ProcObserver",
    "ProcObserverSnapshot",
    "ProcProjection",
    "_store_proc_row",
    "compose_proc_projection",
    "is_monitor_shell_row",
    "proc_projection_for",
]
