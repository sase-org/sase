"""Pure attribution resolver for live ToolRun row chips (plan §§3.3, 3.6).

Attribution is by node kind, never by name-prefix guessing. The live chip
goes to the owner first (monitor or proc row), otherwise the agent turn.
Session containers aggregate their members. Remote rows and clan/tribe
containers never carry a chip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.core.tool_run import ToolRunGlance

_LIVE_STATES = frozenset({"created", "running"})


@dataclass(frozen=True)
class _RowIdentity:
    """Minimal node-kind description for one Agents-tab row."""

    agent_name: str | None = None
    monitor_id: str | None = None
    proc_id: str | None = None
    is_monitor_row: bool = False
    is_proc_row: bool = False
    is_session_container: bool = False
    session_member_names: tuple[str, ...] = ()
    container_name: str | None = None
    is_remote: bool = False
    is_clan: bool = False


def row_identity_from_agent(agent: object) -> _RowIdentity:
    """Build a :class:`_RowIdentity` from an Agents-tab row object.

    Duck-typed so render and cache paths never import the Agent model at
    module load; only the attributes attribution needs are read.
    """

    def _get(name: str) -> object:
        return getattr(agent, name, None)

    agent_name = _get("agent_name")
    monitor_id = _get("monitor_id")
    proc_id = _get("proc_id")
    followups: Any = _get("followup_agents") or ()
    member_names: list[str] = []
    for child in list(followups):
        child_name = getattr(child, "agent_name", None)
        if child_name:
            member_names.append(str(child_name))
    # Runtime children back session aggregation the same way.
    runtime_children: Any = _get("runtime_children") or ()
    for child in list(runtime_children):
        child_name = getattr(child, "agent_name", None)
        if child_name and str(child_name) not in member_names:
            member_names.append(str(child_name))
    container_name: str | None = None
    try:
        ref = getattr(agent, "agent_session_reference_name", None)
        if callable(ref):
            container_name = ref()
    except Exception:
        container_name = None
    return _RowIdentity(
        agent_name=str(agent_name) if agent_name else None,
        monitor_id=str(monitor_id) if monitor_id else None,
        proc_id=str(proc_id) if proc_id else None,
        is_monitor_row=bool(_get("is_monitor")),
        is_proc_row=bool(_get("is_named_proc")),
        is_session_container=bool(_get("is_agent_session_container_row")),
        session_member_names=tuple(member_names),
        container_name=str(container_name) if container_name else None,
        is_remote=bool(_get("fleet_origin_alias")),
        is_clan=bool(_get("is_clan_container")),
    )


def _is_live(run: ToolRunGlance) -> bool:
    return str(getattr(run, "state", "")) in _LIVE_STATES


def _has_no_owner(run: ToolRunGlance) -> bool:
    return not getattr(run, "owner_kind", None)


def _fold_children(
    selected: list[ToolRunGlance],
) -> list[ToolRunGlance]:
    """Fold a live child into its live parent on the same node.

    A live run whose parent run is also live on the same node folds into
    its parent and contributes no ``+N``.
    """

    ids = {str(getattr(run, "run_id", "")) for run in selected}
    folded = [
        run
        for run in selected
        if not (getattr(run, "parent_run_id", None) and str(run.parent_run_id) in ids)
    ]
    # Dedupe by run_id while preserving order.
    seen: set[str] = set()
    unique: list[ToolRunGlance] = []
    for run in folded:
        run_id = str(getattr(run, "run_id", ""))
        if run_id in seen:
            continue
        seen.add(run_id)
        unique.append(run)
    return unique


def select_live_runs(
    runs: object,
    row: _RowIdentity,
) -> tuple[ToolRunGlance, ...]:
    """Return the live runs whose chip belongs on *row* (§3.3).

    Exclusive rules: owner first, then an exact match on a concrete turn's
    ``agent_name``, then an exact match on a session container's name.
    Remote rows and clan containers never match.
    """

    from collections.abc import Sequence as _Sequence

    candidates: _Sequence[ToolRunGlance] = (
        tuple(runs) if isinstance(runs, (list, tuple)) else ()
    )
    live = [run for run in candidates if _is_live(run)]
    if row.is_remote or row.is_clan:
        return ()
    if row.is_monitor_row and row.monitor_id:
        selected = [
            run
            for run in live
            if getattr(run, "owner_kind", None) == "monitor"
            and getattr(run, "owner_id", None) == row.monitor_id
        ]
        return tuple(_fold_children(selected))
    if row.is_proc_row and row.proc_id:
        selected = [
            run
            for run in live
            if getattr(run, "owner_kind", None) == "proc"
            and getattr(run, "owner_id", None) == row.proc_id
        ]
        return tuple(_fold_children(selected))
    if row.is_session_container:
        names = {*row.session_member_names}
        if row.container_name:
            names.add(row.container_name)
        # The container's own agent_name can name the container (§1).
        if row.agent_name:
            names.add(row.agent_name)
        selected = [
            run
            for run in live
            if _has_no_owner(run) and (getattr(run, "agent", None) in names)
        ]
        return tuple(_fold_children(selected))
    if row.agent_name:
        selected = [
            run
            for run in live
            if _has_no_owner(run) and getattr(run, "agent", None) == row.agent_name
        ]
        return tuple(_fold_children(selected))
    return ()


__all__ = ["_RowIdentity", "row_identity_from_agent", "select_live_runs"]
