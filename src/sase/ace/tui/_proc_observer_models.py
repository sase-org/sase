"""Read models the proc observer publishes to the ACE UI.

These types are the whole observer-to-UI contract: an immutable row per proc,
the scoped projection the Procs pane reads, and the typed completion records
the observer thread decodes for durable operations.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult
from sase.procs import ACTIVE_PROC_STATUSES
from sase.project_display_names import humanize_cl_name

from ._proc_observer_log import ObservedProcLog

_ACTIVE_STATUSES = frozenset(ACTIVE_PROC_STATUSES)


def proc_status_is_active(status: str) -> bool:
    """Return whether *status* is one of the active durable proc statuses."""
    return status in _ACTIVE_STATUSES


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
    log: ObservedProcLog = field(default_factory=ObservedProcLog)
    command: list[str] | None = None
    phase: str | None = None
    exit_code: int | None = None
    durable_proc_id: str | None = None
    store_backed: bool = False
    session_id: str | None = None
    session_label: str | None = None
    session_live: bool = True
    origin: str = ""
    # Authoritative combined-log path (``Proc.log_path``). Store-owned rows
    # repeat the store path; a monitor carries ``<artifacts_dir>/live_reply.md``.
    log_path: str = ""
    # Named proc shell (``Proc.shell_name``). For a monitor row
    # (``origin == MONITOR_PROC_ORIGIN``) this is the monitor's member agent
    # name (``acme--mon``).
    shell_name: str | None = None
    lifecycle: str = ""
    project: str | None = None
    workspace_num: int | None = None
    cwd: str = ""
    shell_kind: str | None = None
    request_fingerprint: str | None = None
    reserved_at: datetime | None = None
    supervisor_id: str | None = None
    stop_requested_by: str | None = None
    stop_requested_at: datetime | None = None
    stop_reason: str | None = None
    timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    settling_started_at: datetime | None = None
    settled_by: str | None = None
    settled_at: datetime | None = None
    xprompt_proc: Mapping[str, Any] | None = None

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


def is_monitor_shell_row(row: ObservedProc) -> bool:
    """Return whether an observed row is a ``sase monitor start`` proc shell."""
    return row.origin == MONITOR_PROC_ORIGIN


def monitor_row_agent_name(row: ObservedProc) -> str | None:
    """Return a monitor row's member agent name, or ``None``.

    For ``origin == MONITOR_PROC_ORIGIN`` this is ``ObservedProc.shell_name``
    (the named proc shell, e.g. ``acme--mon``). Non-monitor rows — even ones
    that carry a ``shell_name`` — return ``None``.
    """
    if not is_monitor_shell_row(row):
        return None
    return row.shell_name or None


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
            if proc_status_is_active(row.status)
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
            if proc_status_is_active(row.status) and requested & row.exclusive_scopes:
                return row
        return None


def recount_projection(projection: ProcProjection) -> ProcProjection:
    """Return *projection* with its active and monitor counts recomputed."""
    return replace(
        projection,
        active_count=len(projection.active_rows()),
        active_monitor_count=len(projection.active_monitor_rows()),
    )


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
    return recount_projection(
        ProcProjection(
            rows=tuple(rows),
            session_id=durable.session_id,
        )
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


__all__ = [
    "ObservedProc",
    "ProcCompletionRecord",
    "ProcObserverSnapshot",
    "ProcProjection",
    "compose_proc_projection",
    "is_monitor_shell_row",
    "monitor_row_agent_name",
    "proc_projection_for",
    "proc_status_is_active",
    "recount_projection",
]
