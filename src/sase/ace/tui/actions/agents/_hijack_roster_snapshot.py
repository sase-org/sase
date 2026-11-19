"""Build row-local hijack StopDeps from the in-memory Agents roster.

The TUI path must never fall back to archive walks. Lookups that the
snapshot cannot answer return ``None`` or an empty list.

:func:`hijack_row_local_deps` runs on the UI thread and only copies row
fields. Path canonicalization (a per-component ``lstat`` walk) is deferred
until the hijack worker first calls ``find_session_by_member_artifact_dir``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING, cast

from sase.agent.names import AgentSession, AgentSessionMember, NamedAgent

if TYPE_CHECKING:
    from sase.agent.hijack._stop_models import StopDeps

    from ...models import Agent

_LIVE_STATUSES = frozenset({"STARTING", "RUNNING", "RETRYING", "WAITING", "QUEUED"})
_TERMINAL_STATUSES = frozenset({"DONE", "FAILED", "HIJACKED", "STOPPED", "LOST"})


def hijack_row_local_deps(app: object, agent: Agent) -> StopDeps:
    """Return StopDeps that resolve sessions, clans, and live rows from *app*.

    Called on the UI thread: it snapshots row fields in memory only. The
    artifacts-dir index resolves paths, so it is built lazily on first use,
    which is the dedicated hijack-decision worker.
    """
    snapshots = tuple(_row_snapshot(row) for row in _roster_rows(app, agent))
    by_name = _index_by_name(snapshots)
    by_dir_cache: list[dict[str, SimpleNamespace]] = []

    def by_dir() -> dict[str, SimpleNamespace]:
        if not by_dir_cache:
            by_dir_cache.append(_index_by_artifacts_dir(snapshots))
        return by_dir_cache[0]

    def find_agent(name: str) -> NamedAgent | None:
        snap = by_name.get(name)
        if snap is None or not snap.artifacts_dir:
            return None
        status = str(snap.status or "").upper()
        return NamedAgent(
            name=str(snap.agent_name or name),
            artifacts_dir=str(snap.artifacts_dir),
            is_done=status in _TERMINAL_STATUSES,
            outcome=None,
        )

    def list_running() -> list[Any]:
        return [
            snap
            for snap in snapshots
            if str(snap.status or "").upper() in _LIVE_STATUSES
        ]

    def find_session(name: str) -> AgentSession | None:
        return _session_for_name(name, snapshots)

    def find_session_by_member_artifact_dir(
        path: str | Path,
    ) -> tuple[AgentSession, AgentSessionMember] | None:
        snap = by_dir().get(_canonical_path(path))
        if snap is None:
            return None
        session_name = _session_name(snap)
        if session_name is None:
            return None
        session = _session_for_name(session_name, snapshots)
        if session is None:
            return None
        wanted = _canonical_path(path)
        for member in session.members:
            if _canonical_path(member.artifacts_dir) == wanted:
                return session, member
        return None

    def find_clan(name: str) -> Any | None:
        for snap in snapshots:
            if snap.agent_clan == name:
                return SimpleNamespace(name=name)
            if snap.is_clan_container and (
                snap.agent_name == name or snap.agent_clan == name
            ):
                return SimpleNamespace(name=name)
        return None

    # Duck-typed StopDeps: importing sase.agent.hijack._stop_models here
    # would execute the hijack package's eager __init__ on the UI thread.
    return cast(
        "StopDeps",
        SimpleNamespace(
            find_agent=find_agent,
            list_running=list_running,
            find_session=find_session,
            find_session_by_member_artifact_dir=find_session_by_member_artifact_dir,
            find_clan=find_clan,
            terminate=None,
            snapshot_repo=None,
            now=None,
            process_alive=None,
        ),
    )


def _roster_rows(app: object, agent: Agent) -> list[Agent]:
    """Return the selected row plus roster and follow-up members, de-duplicated."""
    ordered: list[Agent] = []
    seen: set[int] = set()

    def _add(row: Agent | None) -> None:
        if row is None:
            return
        marker = id(row)
        if marker in seen:
            return
        seen.add(marker)
        ordered.append(row)
        for child in getattr(row, "followup_agents", None) or ():
            _add(child)

    _add(agent)
    roster = getattr(app, "_agents_with_children", None)
    if not roster:
        roster = getattr(app, "_agents", None) or ()
    for row in roster:
        _add(row)
    return ordered


def _row_snapshot(row: Agent) -> SimpleNamespace:
    artifacts = getattr(row, "artifacts_dir", None)
    return SimpleNamespace(
        name=getattr(row, "agent_name", None) or getattr(row, "name", None),
        agent_name=getattr(row, "agent_name", None),
        presented_agent_name=getattr(row, "presented_agent_name", None),
        artifacts_dir=str(artifacts) if artifacts else None,
        status=getattr(row, "status", None),
        pid=getattr(row, "pid", None),
        workspace_num=getattr(row, "workspace_num", None),
        agent_session=getattr(row, "agent_session", None),
        agent_session_role=getattr(row, "agent_session_role", None),
        agent_clan=getattr(row, "agent_clan", None),
        is_clan_container=bool(getattr(row, "is_clan_container", False)),
        is_agent_session_container_row=bool(
            getattr(row, "is_agent_session_container_row", False)
        ),
        is_session_container=bool(getattr(row, "is_session_container", False)),
        is_named_proc=bool(getattr(row, "is_named_proc", False)),
        is_remote=bool(getattr(row, "is_remote", False)),
        fleet_origin_alias=getattr(row, "fleet_origin_alias", None),
        is_remote_agent_session_container=bool(
            getattr(row, "is_remote_agent_session_container", False)
        ),
        is_bulk=bool(getattr(row, "is_bulk", False)),
        is_bulk_marked=bool(getattr(row, "is_bulk_marked", False)),
        bulk_marked=bool(getattr(row, "bulk_marked", False)),
        monitor_state=getattr(row, "monitor_state", None),
        parent_timestamp=getattr(row, "parent_timestamp", None),
        raw_suffix=getattr(row, "raw_suffix", None),
        is_workflow_step_child=bool(getattr(row, "is_workflow_step_child", False)),
    )


def _index_by_artifacts_dir(
    snapshots: tuple[SimpleNamespace, ...],
) -> dict[str, SimpleNamespace]:
    index: dict[str, SimpleNamespace] = {}
    for snap in snapshots:
        if snap.artifacts_dir:
            index[_canonical_path(snap.artifacts_dir)] = snap
    return index


def _index_by_name(
    snapshots: tuple[SimpleNamespace, ...],
) -> dict[str, SimpleNamespace]:
    index: dict[str, SimpleNamespace] = {}
    for snap in snapshots:
        for key in (snap.agent_name, snap.name, snap.presented_agent_name):
            if isinstance(key, str) and key:
                index.setdefault(key, snap)
    return index


def _session_name(snap: SimpleNamespace) -> str | None:
    session = snap.agent_session
    if isinstance(session, str) and session:
        return session
    if snap.is_agent_session_container_row or snap.is_session_container:
        name = snap.agent_name
        if isinstance(name, str) and name:
            return name
    return None


def _session_for_name(
    name: str, snapshots: tuple[SimpleNamespace, ...]
) -> AgentSession | None:
    session_name: str | None = None
    for snap in snapshots:
        if snap.agent_session == name or snap.agent_name == name:
            session_name = snap.agent_session or name
            break
        if (snap.is_agent_session_container_row or snap.is_session_container) and (
            snap.agent_session == name or snap.agent_name == name
        ):
            session_name = snap.agent_session or snap.agent_name
            break
    if not isinstance(session_name, str) or not session_name:
        return None
    members: list[AgentSessionMember] = []
    root: AgentSessionMember | None = None
    for snap in snapshots:
        if snap.agent_session != session_name and snap.agent_name != session_name:
            continue
        if not snap.artifacts_dir:
            continue
        artifacts = Path(snap.artifacts_dir)
        timestamp = str(snap.raw_suffix or artifacts.name)
        member = AgentSessionMember(
            name=str(snap.agent_name or snap.name or session_name),
            artifacts_dir=artifacts,
            timestamp=timestamp,
            outcome=None,
            parent_timestamp=snap.parent_timestamp
            if isinstance(snap.parent_timestamp, str)
            else None,
        )
        members.append(member)
        if snap.agent_session_role == "root":
            root = member
    if not members:
        return None
    return AgentSession(
        base_name=session_name,
        root=root or members[0],
        members=tuple(members),
    )


def _canonical_path(value: str | Path) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(value)


__all__ = ["hijack_row_local_deps"]
