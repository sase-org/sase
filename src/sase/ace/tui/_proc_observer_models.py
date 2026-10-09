"""Read models the proc observer publishes to the ACE UI.

These types are the whole observer-to-UI contract: an immutable row per proc,
the scoped projection the Procs pane reads, and the typed completion records
the observer thread decodes for durable operations.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.ops import DurableOperationResult
from sase.procs import ACTIVE_PROC_STATUSES
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_ONESHOT_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
    ProcServiceBlock,
    host_service_tag_name,
)
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
    # Named named proc (``Proc.proc_name``). For a monitor row
    # (``origin == MONITOR_PROC_ORIGIN``) this is the monitor's member agent
    # name (``acme--mon``).
    proc_name: str | None = None
    lifecycle: str = ""
    project: str | None = None
    workspace_num: int | None = None
    cwd: str = ""
    proc_role: str | None = None
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
    prompt_proc: Mapping[str, Any] | None = None
    service: ProcServiceBlock | None = None
    tags: tuple[str, ...] = ()

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


def is_monitor_turn_row(row: ObservedProc) -> bool:
    """Return whether an observed row is a ``sase monitor start`` named proc."""
    return row.origin == MONITOR_PROC_ORIGIN


def is_service_row(row: ObservedProc) -> bool:
    """Return whether a row is owned by the service host or is a oneshot.

    The wire ``service`` block is authoritative, but it is an additive field: a
    ``sase_core_rs`` build that predates it drops the block silently while the
    host-written ``origin`` still round-trips. Falling back to the origin keeps
    such rows (including ones already in the store) classified correctly.
    """
    return row.service is not None or row.origin in (
        SERVICE_HOST_ORIGIN,
        SERVICE_ONESHOT_ORIGIN,
    )


def service_row_name(row: ObservedProc) -> str | None:
    """Return the service proc a row runs, if it names one.

    Without a ``service`` block, a host-written daemon row is still named by
    its ``service:<name>`` label (see :func:`is_service_row`).
    """
    if row.service is not None:
        return row.service.name or None
    if row.origin != SERVICE_HOST_ORIGIN:
        return None
    return host_service_tag_name((row.label,))


def is_service_daemon_row(row: ObservedProc) -> bool:
    """Return whether a row is a service daemon that never terminates.

    Without a ``service`` block the host origin still identifies a daemon: the
    host reserves daemons and nothing else under it, and a transient oneshot is
    never one. ``proc_role == "service"`` is deliberately not a third signal;
    it is redundant with the origin on every row the host writes.
    """
    if row.service is not None:
        return row.service.mode == SERVICE_PROC_MODE_DAEMON
    return row.origin == SERVICE_HOST_ORIGIN


def is_gear_eligible_row(row: ObservedProc) -> bool:
    """Return whether an active row counts toward the blue ``bg:`` gear.

    Monitor turns and service rows have their own surfaces (see
    :func:`is_service_row` for how a service row is recognized); ownership is
    never inferred from ``session_id``. Callers still gate on the row being
    active.
    """
    return not is_monitor_turn_row(row) and not is_service_row(row)


# Proc types that plan or apply a change to the installed SASE stack
# (as opposed to sync/mail-style work). Session-worker types cover live
# workers; ``plugin.update`` is the durable operation name reused as the
# pending-placeholder proc type before its ``plugin-update:`` scope lands.
UPDATE_PROC_TYPES = frozenset(
    {
        "update-preview",
        "comprehensive-update",
        "sase-update",
        "dev-update",
        "agent-cli-update",
        "mode-switch",
        "plugin.update",
    }
)
# Durable concurrency keys marking the same lane. Session proc types cover
# live workers; scopes cover durable store rows (notably plugin updates,
# whose store rows carry a generic kind) and pending placeholders.
UPDATE_EXCLUSIVE_SCOPES = frozenset({"sase-update", "agent-cli-update"})
PLUGIN_UPDATE_SCOPE_PREFIX = "plugin-update:"
PLUGIN_INSTALL_SCOPE_PREFIX = "plugin-install:"
PLUGIN_UNINSTALL_SCOPE_PREFIX = "plugin-uninstall:"
INSTALL_MUTATION_PROC_TYPES = UPDATE_PROC_TYPES | frozenset(
    {"plugin.install", "plugin.uninstall"}
)

# Tag vocabulary shared with ``sase.tool.handoff`` (``owner_tags`` /
# ``join_tags``). Kept as literals so this UI-side module never imports the
# tool-launch path; ``procs_pane_render`` carries the same pair.
TOOL_RUN_PROC_ORIGIN = "tool-run"
TOOL_RUN_OWNER_TAG = "tool-run"
TOOL_RUN_OWNER_TAG_PREFIX = "tool-run:"
TOOL_RUN_JOIN_TAG_PREFIX = "tool-run-join:"

GearLane = Literal["bg", "tool", "monitor", "update"]


def _is_tool_run_carrier(row: ObservedProc) -> bool:
    """Return whether a proc row carries a live ToolRun execution.

    Carriers are ``tool-run`` procs, adopt monitors (``tool-run`` /
    ``tool-run:<id>`` tags) and join monitors (``tool-run-join:<id>``).
    Classification uses only ``origin`` and exact tags — never
    ``session_id``, labels, or command prefixes.
    """
    if row.origin == TOOL_RUN_PROC_ORIGIN:
        return True
    for tag in tuple(getattr(row, "tags", None) or ()):
        if not isinstance(tag, str):
            continue
        if tag == TOOL_RUN_OWNER_TAG:
            return True
        if tag.startswith(TOOL_RUN_OWNER_TAG_PREFIX):
            # ``tool-run-join:<id>`` does not start with ``tool-run:``;
            # the join prefix is checked explicitly below.
            return True
        if tag.startswith(TOOL_RUN_JOIN_TAG_PREFIX):
            return True
    return False


def _tool_run_ids_for_row(row: ObservedProc) -> frozenset[str]:
    """Return the distinct ToolRun ids a carrier row references via tags."""
    ids: set[str] = set()
    for tag in tuple(getattr(row, "tags", None) or ()):
        if not isinstance(tag, str):
            continue
        if tag.startswith(TOOL_RUN_JOIN_TAG_PREFIX):
            run_id = tag[len(TOOL_RUN_JOIN_TAG_PREFIX) :].strip()
        elif tag.startswith(TOOL_RUN_OWNER_TAG_PREFIX):
            run_id = tag[len(TOOL_RUN_OWNER_TAG_PREFIX) :].strip()
        else:
            continue
        if run_id:
            ids.add(run_id)
    return frozenset(ids)


def is_update_row(row: ObservedProc) -> bool:
    """Return whether a gear-eligible row is in the SASE-update lane.

    Callers still gate on the row being active.
    """
    if not is_gear_eligible_row(row):
        return False
    if row.proc_type in UPDATE_PROC_TYPES:
        return True
    return any(
        scope in UPDATE_EXCLUSIVE_SCOPES or scope.startswith(PLUGIN_UPDATE_SCOPE_PREFIX)
        for scope in row.exclusive_scopes
    )


def is_install_mutation_row(row: ObservedProc) -> bool:
    """Return whether a row mutates the installed SASE stack.

    Plugin install/uninstall are included even though they are not
    update-lane rows. Callers still gate on the row being active.
    """
    if is_monitor_turn_row(row) or is_service_daemon_row(row):
        return False
    if row.proc_type in INSTALL_MUTATION_PROC_TYPES:
        return True
    return any(
        scope in UPDATE_EXCLUSIVE_SCOPES
        or scope.startswith(PLUGIN_UPDATE_SCOPE_PREFIX)
        or scope.startswith(PLUGIN_INSTALL_SCOPE_PREFIX)
        or scope.startswith(PLUGIN_UNINSTALL_SCOPE_PREFIX)
        for scope in row.exclusive_scopes
    )


def proc_gear_lane(
    row: ObservedProc, *, tool_run_owner_proc_ids: frozenset[str] = frozenset()
) -> GearLane | None:
    """Return the gear lane for one row.

    A proc that carries a live ToolRun is in the ``"tool"`` lane and is
    never drawn as a gear. Carrier monitors read as ``"tool"``; bare
    monitor turns read as ``"monitor"``; service rows read as ``None``;
    update-lane rows read as ``"update"``; everything else reads as
    ``"bg"`` (the TUI's own background work). Callers still gate on the
    row being active.
    """
    if is_monitor_turn_row(row):
        if _is_tool_run_carrier(row):
            return "tool"
        return "monitor"
    if is_service_row(row):
        return None
    if is_update_row(row):
        return "update"
    if _is_tool_run_carrier(row):
        return "tool"
    proc_id = row.durable_proc_id or row.proc_id
    if proc_id and proc_id in tool_run_owner_proc_ids:
        # The ``: tool run`` Command Line case: an ``ace`` proc that owns a
        # live glance run is drawn once, in the tool lane.
        return "tool"
    return "bg"


@dataclass(frozen=True)
class ProcGearLanes:
    """Split of active gear-eligible rows into top-bar lanes."""

    bg: int = 0
    tool_procs: int = 0
    monitors: int = 0
    update_rows: tuple[ObservedProc, ...] = ()
    bg_rows: tuple[ObservedProc, ...] = ()
    monitor_rows: tuple[ObservedProc, ...] = ()
    tool_run_ids: frozenset[str] = frozenset()

    @property
    def procs(self) -> int:
        """Back-compat alias for the ``bg`` lane count."""
        return self.bg

    @property
    def updates(self) -> int:
        """Number of active update-lane rows."""
        return len(self.update_rows)

    @property
    def update_labels(self) -> tuple[str, ...]:
        """User-facing labels for active update rows, oldest first."""
        return tuple(row.label for row in self.update_rows)

    @property
    def bg_labels(self) -> tuple[str, ...]:
        """User-facing labels for active background rows, oldest first."""
        return tuple(row.label for row in self.bg_rows)

    @property
    def monitor_names(self) -> tuple[str, ...]:
        """Member names of bare-monitor rows, oldest first."""
        return tuple(
            monitor_row_agent_name(row) or row.label for row in self.monitor_rows
        )


def proc_gear_lanes(
    projection: ProcProjection,
    *,
    all_sessions: bool = False,
    tool_run_owner_proc_ids: frozenset[str] = frozenset(),
) -> ProcGearLanes:
    """Split active rows into bg/tool/monitor/update lanes in one pass."""
    bg = 0
    tool_procs = 0
    monitors = 0
    bg_rows: list[ObservedProc] = []
    monitor_rows: list[ObservedProc] = []
    update_rows: list[ObservedProc] = []
    tool_run_ids: set[str] = set()
    for row in projection.active_rows(all_sessions=all_sessions):
        lane = proc_gear_lane(row, tool_run_owner_proc_ids=tool_run_owner_proc_ids)
        if lane == "monitor":
            monitors += 1
            monitor_rows.append(row)
        elif lane == "update":
            update_rows.append(row)
        elif lane == "tool":
            tool_procs += 1
            tool_run_ids.update(_tool_run_ids_for_row(row))
        elif lane == "bg":
            bg += 1
            bg_rows.append(row)
    update_rows.sort(key=lambda item: item.started_at)
    bg_rows.sort(key=lambda item: item.started_at)
    monitor_rows.sort(key=lambda item: item.started_at)
    return ProcGearLanes(
        bg=bg,
        tool_procs=tool_procs,
        monitors=monitors,
        update_rows=tuple(update_rows),
        bg_rows=tuple(bg_rows),
        monitor_rows=tuple(monitor_rows),
        tool_run_ids=frozenset(tool_run_ids),
    )


def monitor_row_agent_name(row: ObservedProc) -> str | None:
    """Return a monitor row's member agent name, or ``None``.

    For ``origin == MONITOR_PROC_ORIGIN`` this is ``ObservedProc.proc_name``
    (the named named proc, e.g. ``acme--mon``). Non-monitor rows — even ones
    that carry a ``proc_name`` — return ``None``.
    """
    if not is_monitor_turn_row(row):
        return None
    return row.proc_name or None


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
        """Return active rows that are ``sase monitor start`` named procs."""
        return [
            row
            for row in self.active_rows(all_sessions=all_sessions)
            if is_monitor_turn_row(row)
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
class ProcExitCompletion:
    """One terminal exit observed without decoding any typed result.

    The Command Line watches ordinary procs (which leave no result
    envelope) this way: the completion settles purely from the store row's
    ``status``, ``exit_code`` and ``finished_at``.
    """

    proc_id: str
    status: str
    exit_code: int | None = None
    finished_at: datetime | None = None
    placeholder_id: str | None = None


@dataclass(frozen=True)
class ProcObserverSnapshot:
    """Immutable observer-to-UI delivery record."""

    projection: ProcProjection
    completions: tuple[ProcCompletionRecord, ...] = ()
    exit_completions: tuple[ProcExitCompletion, ...] = ()


__all__ = [
    "TOOL_RUN_JOIN_TAG_PREFIX",
    "TOOL_RUN_OWNER_TAG",
    "TOOL_RUN_OWNER_TAG_PREFIX",
    "TOOL_RUN_PROC_ORIGIN",
    "GearLane",
    "INSTALL_MUTATION_PROC_TYPES",
    "ObservedProc",
    "PLUGIN_INSTALL_SCOPE_PREFIX",
    "PLUGIN_UNINSTALL_SCOPE_PREFIX",
    "PLUGIN_UPDATE_SCOPE_PREFIX",
    "ProcCompletionRecord",
    "ProcExitCompletion",
    "ProcGearLanes",
    "ProcObserverSnapshot",
    "ProcProjection",
    "UPDATE_EXCLUSIVE_SCOPES",
    "UPDATE_PROC_TYPES",
    "compose_proc_projection",
    "is_gear_eligible_row",
    "is_install_mutation_row",
    "is_monitor_turn_row",
    "is_service_daemon_row",
    "is_service_row",
    "is_update_row",
    "monitor_row_agent_name",
    "proc_gear_lane",
    "proc_gear_lanes",
    "proc_projection_for",
    "proc_status_is_active",
    "recount_projection",
    "service_row_name",
]
