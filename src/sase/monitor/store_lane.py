"""Lane and caller resolution, and lane-scoped monitor queries.

Resolves a lane name, an explicit agent name, or the calling agent's own
identity to the artifact record that anchors it. Built on top of
:mod:`sase.monitor.store`'s artifact-index queries, referenced through the
``store`` module itself (never imported by name) so tests that monkeypatch
``sase.monitor.store.project_records`` (and friends) continue to control what
these lookups see.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.plan_chain import agent_family_base
from sase.procs.models import ProcStoreSnapshot

from . import store
from .models import MonitorLaneError, MonitorRecord, is_monitor_member_record
from .reconcile import reconcile_dead_supervisor, should_reconcile_dead_supervisor


@dataclass(frozen=True)
class LaneContext:
    """A resolved agent artifact used as a monitor parent or lane member."""

    lane: str
    project_name: str
    record: AgentArtifactRecordWire


def default_caller(env: Mapping[str, str] | None = None) -> str | None:
    """Return the calling agent's exact name from its environment, if any.

    This does not collapse the name through
    :func:`~sase.plan_chain.agent_family_base`: :func:`resolve_caller_agent`
    resolves a durable family from the caller's own artifacts instead, so a
    phase name such as ``sase-m6.6.1.5`` is never rewritten into a broader
    family lane.
    """
    current_env = env if env is not None else os.environ
    name = current_env.get("SASE_AGENT_NAME")
    if not name:
        return None
    name = name.strip()
    return name or None


def caller_artifacts_dir(env: Mapping[str, str] | None = None) -> str | None:
    """Return the calling agent shell's own artifacts dir, if the env names one.

    ``SASE_ARTIFACTS_DIR`` is set for every agent shell and points at exactly
    the artifact record that is running -- the most precise identity
    available, and one that needs no name reasoning at all.
    """
    current_env = env if env is not None else os.environ
    value = current_env.get("SASE_ARTIFACTS_DIR")
    if not value:
        return None
    value = value.strip()
    return value or None


def resolve_caller_agent(
    project_name: str,
    caller: str,
    *,
    artifacts_dir: str | None = None,
) -> LaneContext:
    """Resolve the artifact record of the agent shell calling right now.

    Mirrors :func:`sase.agent.identity.resolve_local_agent_name`'s
    metadata-first resolution: family members can replace one another
    inside a single process, leaving ``SASE_AGENT_NAME`` set to the
    family/container while this run's own artifacts carry the concrete
    agent shell. Tried in order:

    1. *artifacts_dir* (the caller's own ``SASE_ARTIFACTS_DIR``), when the
       record it names belongs to *caller* -- a stale or foreign value
       falls through to the next step instead of hijacking resolution.
    2. An exact ``agent_meta.name`` match for *caller* (bare agents, and
       callers whose env already carries the member name, e.g.
       ``02i--code``).
    3. The newest non-monitor member of *caller*'s own family -- records
       whose ``agent_meta.agent_family`` equals *caller* exactly. Monitor
       members are excluded so a settled ``--mon`` row, usually the newest
       member of the family, is never selected as the parent.

    Raises :class:`MonitorLaneError` naming ``-a/--agent`` when none of the
    above resolves.
    """
    records = store.project_records(project_name)

    pinned = _pinned_caller_record(records, caller, artifacts_dir)
    if pinned is not None:
        return LaneContext(lane=caller, project_name=project_name, record=pinned)

    exact = [record for record in records if _record_has_name(record, caller)]
    if exact:
        newest = max(exact, key=lambda record: record.timestamp)
        return LaneContext(lane=caller, project_name=project_name, record=newest)

    family_members = [
        record
        for record in records
        if _record_family_is(record, caller) and not is_monitor_member_record(record)
    ]
    if family_members:
        newest = max(family_members, key=lambda record: record.timestamp)
        return LaneContext(lane=caller, project_name=project_name, record=newest)

    raise MonitorLaneError(_no_caller_artifacts_message(project_name, caller, records))


def resolve_lane(project_name: str, lane: str) -> LaneContext:
    """Resolve *lane* to its newest family member's artifact record."""
    records = [
        record
        for record in store.project_records(project_name)
        if _record_in_lane(record, lane)
    ]
    if not records:
        raise MonitorLaneError(
            f"no agent artifacts found for lane {lane!r} in project {project_name!r}"
        )
    newest = max(records, key=lambda record: record.timestamp)
    return LaneContext(lane=lane, project_name=project_name, record=newest)


def resolve_exact_agent(project_name: str, agent_name: str) -> LaneContext:
    """Resolve *agent_name* to the newest artifact with that exact name."""
    records = [
        record
        for record in store.project_records(project_name)
        if _record_has_name(record, agent_name)
    ]
    if not records:
        raise MonitorLaneError(
            f"no agent artifacts found for agent {agent_name!r} "
            f"in project {project_name!r}"
        )
    newest = max(records, key=lambda record: record.timestamp)
    return LaneContext(lane=agent_name, project_name=project_name, record=newest)


def durable_lane_for_record(record: AgentArtifactRecordWire, *, fallback: str) -> str:
    """Return the durable monitor lane for *record*.

    Prefers persisted ``agent_family`` metadata. A still-bare agent falls
    back to *fallback* (the exact caller name or an explicit lane) rather
    than guessing from the spelling of ``name``.
    """
    meta = record.agent_meta
    if meta is not None:
        family = (meta.agent_family or "").strip()
        if family:
            return family
    return fallback


class _LazyProcSnapshot:
    """Read the durable proc store at most once for one lane scan.

    The dead-supervisor guard consults the proc store for every candidate
    record. Sharing one snapshot keeps a lane scan at a single store read
    instead of one per candidate, and deferring the read keeps lanes with
    no monitor member from touching the store at all.
    """

    def __init__(self) -> None:
        self._snapshot: ProcStoreSnapshot | None = None

    def get(self) -> ProcStoreSnapshot:
        if self._snapshot is None:
            from sase.procs.store import read_proc_snapshot

            self._snapshot = read_proc_snapshot()
        return self._snapshot


def active_monitor_for_lane(
    project_name: str, lane: str
) -> AgentArtifactRecordWire | None:
    """Return the not-yet-terminal monitor member for *lane*, if any."""
    procs = _LazyProcSnapshot()
    candidates: list[AgentArtifactRecordWire] = []
    for record in store.monitor_records(project_name):
        meta = record.agent_meta
        if meta is None or meta.agent_family != lane:
            continue
        try:
            monitor = MonitorRecord.from_record(record)
        except ValueError:
            continue
        if should_reconcile_dead_supervisor(monitor, snapshot=procs.get()):
            monitor = reconcile_dead_supervisor(
                monitor, get_monitor=store.read_monitor_marker, snapshot=procs.get()
            )
        if not monitor.is_terminal:
            candidates.append(record)
    if not candidates:
        return None
    return max(candidates, key=lambda record: record.timestamp)


def monitor_blocking_start_for_lane(
    project_name: str,
    lane: str,
) -> MonitorRecord | None:
    """Return the monitor that prevents starting a new one in *lane*.

    Same-boot dead supervisors are reconciled to terminal ``failed`` records
    and do not block replacement. Pre-reboot monitors reconcile to ``lost``
    and do block replacement because the command's effect is unknown.
    """
    procs = _LazyProcSnapshot()
    candidates: list[MonitorRecord] = []
    for record in store.monitor_records(project_name):
        meta = record.agent_meta
        if meta is None or meta.agent_family != lane:
            continue
        try:
            monitor = MonitorRecord.from_record(record)
        except ValueError:
            continue
        if monitor.is_terminal:
            continue
        if should_reconcile_dead_supervisor(monitor, snapshot=procs.get()):
            monitor = reconcile_dead_supervisor(
                monitor, get_monitor=store.read_monitor_marker, snapshot=procs.get()
            )
        if monitor.monitor_state == "lost" or not monitor.is_terminal:
            candidates.append(monitor)
    if not candidates:
        return None
    return max(candidates, key=lambda record: record.timestamp)


def has_any_monitor(project_name: str, lane: str) -> bool:
    """Return whether *lane* has ever had a monitor member."""
    return any(
        record.agent_meta is not None and record.agent_meta.agent_family == lane
        for record in store.monitor_records(project_name)
    )


def _record_in_lane(record: AgentArtifactRecordWire, lane: str) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    if meta.agent_family == lane or meta.workflow_name == lane:
        return True
    return meta.name == lane or agent_family_base(meta.name) == lane


def _record_has_name(record: AgentArtifactRecordWire, agent_name: str) -> bool:
    meta = record.agent_meta
    return meta is not None and meta.name == agent_name


def _record_family_is(record: AgentArtifactRecordWire, family: str) -> bool:
    meta = record.agent_meta
    return meta is not None and meta.agent_family == family


def _pinned_caller_record(
    records: Sequence[AgentArtifactRecordWire],
    caller: str,
    artifacts_dir: str | None,
) -> AgentArtifactRecordWire | None:
    """Return the record at *artifacts_dir* if it belongs to *caller*.

    A record only counts as pinned when its own name, family, or family
    base matches the caller -- a stale or foreign ``SASE_ARTIFACTS_DIR``
    must fall through to the name/family steps instead of hijacking start.
    """
    if not artifacts_dir:
        return None
    for record in records:
        if not _same_artifact_dir(record.artifact_dir, artifacts_dir):
            continue
        meta = record.agent_meta
        if meta is None:
            return None
        if (
            meta.name == caller
            or meta.agent_family == caller
            or agent_family_base(meta.name) == caller
        ):
            return record
        return None
    return None


def _same_artifact_dir(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve(strict=False) == Path(
            right
        ).expanduser().resolve(strict=False)
    except OSError:
        return left.rstrip("/") == right.rstrip("/")


def _no_caller_artifacts_message(
    project_name: str, caller: str, records: Sequence[AgentArtifactRecordWire]
) -> str:
    base = (
        f"no artifacts found for the calling agent {caller!r} in project "
        f"{project_name!r}; pass -a/--agent explicitly"
    )
    nearest = _nearest_caller_artifact_names(records, caller)
    if not nearest:
        return base
    return f"{base} (nearest artifacts: {', '.join(nearest)})"


def _nearest_caller_artifact_names(
    records: Sequence[AgentArtifactRecordWire], caller: str
) -> list[str]:
    """Return up to five near-miss names for *caller*, newest first."""
    candidates = [
        record
        for record in records
        if record.agent_meta is not None
        and record.agent_meta.name
        and (
            record.agent_meta.name.startswith(caller)
            or record.agent_meta.agent_family == caller
        )
    ]
    candidates.sort(key=lambda record: record.timestamp, reverse=True)
    names: list[str] = []
    for record in candidates[:5]:
        meta = record.agent_meta
        if meta is not None and meta.name:
            names.append(meta.name)
    return names


__all__ = [
    "LaneContext",
    "active_monitor_for_lane",
    "caller_artifacts_dir",
    "default_caller",
    "durable_lane_for_record",
    "has_any_monitor",
    "monitor_blocking_start_for_lane",
    "resolve_caller_agent",
    "resolve_exact_agent",
    "resolve_lane",
]
