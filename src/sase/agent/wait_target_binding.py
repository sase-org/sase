"""Bind a wait reference to a pinned v2 identity record.

``%wait``, ``sase agent wait``, and ``#fork`` all call
:func:`bind_wait_target` so a session's current turn is captured once, at
bind time, and later evaluation never re-resolves the name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.fork_waits import artifact_identity, resolved_proc_id
from sase.agent.names import (
    AgentSession,
    NamedAgent,
    find_agent_clan,
    find_agent_session,
    find_agent_session_by_member_artifact_dir,
    find_named_agent,
)
from sase.agent.names._lookup_artifacts import read_json_dict
from sase.core.agent_identity_facade import (
    AgentSessionNameKind,
    parse_agent_session_name,
)
from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
)
from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.core.wait_dependency_resolution._types import ArtifactCandidate
from sase.plan_chain import agent_session_role_value
from sase.core.wait_target_facade import (
    EffectiveWaitTarget,
    WaitReferenceKindName,
    WaitScopeName,
    WaitTargetName,
    WaitTurnFacts,
    effective_wait_target,
    parse_wait_target,
    select_current_wait_turn,
)
from sase.monitor_state import is_real_monitor_member


@dataclass(frozen=True, slots=True)
class WaitTargetBinding:
    """Pinned v2 wait fields for one classified reference."""

    requested: str
    name: str
    kind: WaitReferenceKindName
    target: WaitTargetName
    target_explicit: bool
    scope: WaitScopeName
    artifact_dir: str | None = None
    timestamp: str | None = None
    project_name: str | None = None
    turn_name: str | None = None
    identity_record: dict[str, Any] | None = None


def bind_wait_target(
    reference: str,
    *,
    requested_target: str | None = None,
    waiter_artifact_dir: str | Path | None = None,
    index: WaitDependencyIndex | None = None,
) -> WaitTargetBinding:
    """Classify *reference*, apply the effective-target table, and pin identity."""
    parsed_target = (
        parse_wait_target(requested_target) if requested_target is not None else None
    )
    kind, agent, session = _classify_reference(reference)
    effective = effective_wait_target(
        requested=parsed_target,
        kind=kind,
        reference=reference,
    )
    pin_dir, pin_name, turn_name = _pin_for_effective(
        reference,
        kind=kind,
        agent=agent,
        session=session,
        effective=effective,
        waiter_artifact_dir=waiter_artifact_dir,
        index=index,
    )
    identity = artifact_identity(pin_dir) if pin_dir is not None else {}
    record = None
    if pin_dir is not None and _needs_identity_record(effective, kind):
        record = _v2_identity_record(
            requested=reference,
            name=pin_name,
            target=effective.target,
            target_explicit=effective.explicit,
            identity=identity,
            turn_name=turn_name,
        )
    return WaitTargetBinding(
        requested=reference,
        name=pin_name,
        kind=kind,
        target=effective.target,
        target_explicit=effective.explicit,
        scope=effective.scope,
        artifact_dir=identity.get("artifact_dir"),
        timestamp=identity.get("timestamp"),
        project_name=identity.get("project_name"),
        turn_name=turn_name,
        identity_record=record,
    )


def bind_explicit_wait_targets(
    wait_targets: Mapping[str, str],
    *,
    waiter_artifact_dir: str | Path | None = None,
    index: WaitDependencyIndex | None = None,
) -> list[dict[str, Any]]:
    """Return v2 identity records for each explicit ``{name: target}`` entry."""
    records: list[dict[str, Any]] = []
    shared_index = index
    for name, target in wait_targets.items():
        binding = bind_wait_target(
            name,
            requested_target=target,
            waiter_artifact_dir=waiter_artifact_dir,
            index=shared_index,
        )
        if shared_index is None and binding.artifact_dir:
            shared_index = _wait_index_for(Path(binding.artifact_dir), None)
        if binding.identity_record is not None:
            records.append(dict(binding.identity_record))
    return records


def _classify_reference(
    reference: str,
) -> tuple[WaitReferenceKindName, NamedAgent | None, AgentSession | None]:
    if find_agent_clan(reference) is not None:
        return "clan", None, None
    try:
        tribe = parse_tribe_reference(reference)
    except InvalidTribeError as exc:
        raise RuntimeError(str(exc)) from exc
    if tribe is not None:
        return "tribe", None, None

    try:
        parsed = parse_agent_session_name(reference)
        is_member = parsed.kind is AgentSessionNameKind.MEMBER
    except (RuntimeError, ValueError):
        is_member = False

    agent = find_named_agent(reference)
    if is_member:
        if agent is None:
            return "unresolved", None, None
        return "exact_member", agent, None

    if agent is not None and _is_proc_or_monitor(agent):
        return "proc", agent, None
    if resolved_proc_id(reference) is not None:
        return "proc", agent, None

    session = find_agent_session(reference)
    if session is not None or agent is not None:
        return "bare_agent", agent, session
    return "unresolved", None, None


def _pin_for_effective(
    reference: str,
    *,
    kind: WaitReferenceKindName,
    agent: NamedAgent | None,
    session: AgentSession | None,
    effective: EffectiveWaitTarget,
    waiter_artifact_dir: str | Path | None,
    index: WaitDependencyIndex | None,
) -> tuple[Path | None, str, str | None]:
    """Return ``(pin_dir, record_name, turn_name)`` for the effective scope."""
    if not _needs_identity_record(effective, kind):
        return None, _display_name(reference, agent, session), None

    if effective.scope == "member":
        if agent is None:
            raise RuntimeError(
                f"Cannot pin wait {reference!r} to a member: agent not found"
            )
        return Path(agent.artifacts_dir), agent.name, agent.name

    if effective.scope == "session" and kind == "exact_member":
        if agent is None:
            raise RuntimeError(
                f"Cannot pin wait {reference!r} to a session: agent not found"
            )
        root_dir, session_name = _owning_session_root(agent)
        return root_dir, session_name, None

    if effective.scope == "current_turn":
        return _pin_current_turn(
            reference,
            agent=agent,
            session=session,
            waiter_artifact_dir=waiter_artifact_dir,
            index=index,
        )

    raise RuntimeError(f"Cannot pin wait {reference!r} with scope {effective.scope!r}")


def _pin_current_turn(
    reference: str,
    *,
    agent: NamedAgent | None,
    session: AgentSession | None,
    waiter_artifact_dir: str | Path | None,
    index: WaitDependencyIndex | None,
) -> tuple[Path, str, str]:
    root_dir = _current_turn_root_dir(reference, agent, session)
    session_name = (
        session.base_name
        if session is not None
        else (agent.name if agent is not None else reference)
    )
    wait_index = _wait_index_for(root_dir, index)
    root = _candidate_for_dir(wait_index, root_dir)
    if root is None:
        # Session of one whose row is not yet indexed: the root is the turn.
        turn_name = agent.name if agent is not None else reference
        return root_dir, session_name, turn_name

    members = _generation_members(wait_index, root)
    waiter_key = (
        artifact_dir_key(str(waiter_artifact_dir))
        if waiter_artifact_dir is not None
        else None
    )
    facts: list[WaitTurnFacts] = []
    for member in members:
        is_waiter = (
            waiter_key is not None
            and artifact_dir_key(member.artifact_dir) == waiter_key
        )
        facts.append(
            WaitTurnFacts(
                member.timestamp,
                pending=_turn_member_is_pending(member) or member.is_queued,
                excluded=is_waiter or member.is_dependency_parked,
            )
        )
    selected = select_current_wait_turn(facts)
    if selected is None:
        raise RuntimeError(
            f"Cannot pin a current turn for {reference!r}: no eligible session member"
        )
    chosen = members[selected]
    turn_name = chosen.name or reference
    return Path(chosen.artifact_dir), session_name, turn_name


def _current_turn_root_dir(
    reference: str,
    agent: NamedAgent | None,
    session: AgentSession | None,
) -> Path:
    if session is not None and session.root is not None:
        return Path(session.root.artifacts_dir)
    if session is not None and session.members:
        oldest = min(session.members, key=lambda member: member.timestamp)
        return Path(oldest.artifacts_dir)
    if agent is not None:
        return Path(agent.artifacts_dir)
    raise RuntimeError(
        f"Cannot pin a current turn for {reference!r}: no session members"
    )


def _owning_session_root(agent: NamedAgent) -> tuple[Path, str]:
    found = find_agent_session_by_member_artifact_dir(agent.artifacts_dir)
    if found is not None:
        session, _member = found
        if session.root is not None:
            return Path(session.root.artifacts_dir), session.base_name
        return Path(agent.artifacts_dir), session.base_name
    try:
        parsed = parse_agent_session_name(agent.name)
        session_name = parsed.agent_session_name or agent.name
    except (RuntimeError, ValueError):
        session_name = agent.name
    return Path(agent.artifacts_dir), session_name


def _needs_identity_record(
    effective: EffectiveWaitTarget,
    kind: WaitReferenceKindName,
) -> bool:
    if effective.scope in {"current_turn", "member"}:
        return True
    return (
        kind == "exact_member" and effective.target == "session" and effective.explicit
    )


def _display_name(
    reference: str,
    agent: NamedAgent | None,
    session: AgentSession | None,
) -> str:
    if session is not None:
        return session.base_name
    if agent is not None:
        return agent.name
    return reference


def _v2_identity_record(
    *,
    requested: str,
    name: str,
    target: WaitTargetName,
    target_explicit: bool,
    identity: Mapping[str, str],
    turn_name: str | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_version": 2,
        "requested": requested,
        "name": name,
        "target": target,
        "target_explicit": target_explicit,
        **dict(identity),
    }
    if turn_name:
        record["turn_name"] = turn_name
    return record


def _turn_member_is_pending(candidate: ArtifactCandidate) -> bool:
    """Return whether a session member may still run or change its outcome."""
    return not (
        candidate.has_done_marker
        or candidate.archived_completion is not None
        or candidate.is_resolved
    )


def _is_proc_or_monitor(agent: NamedAgent) -> bool:
    meta = read_json_dict(Path(agent.artifacts_dir) / "agent_meta.json") or {}
    monitor_id = meta.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        return False
    role = agent_session_role_value(meta)
    session_role = role if isinstance(role, str) and role else None
    return is_real_monitor_member(session_role, monitor_id)


def _wait_index_for(
    artifact_dir: Path,
    index: WaitDependencyIndex | None,
) -> WaitDependencyIndex:
    if index is not None:
        return index
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    info = parse_agent_artifact_path(artifact_dir)
    if info is None or not info.project_name:
        return WaitDependencyIndex.empty()
    return build_wait_dependency_index(info.project_name)


def _candidate_for_dir(
    index: WaitDependencyIndex,
    artifact_dir: Path,
) -> ArtifactCandidate | None:
    found = index.artifacts_by_dir.get(str(artifact_dir))
    if found is not None:
        return found
    target = artifact_dir_key(str(artifact_dir))
    for candidate in index.artifacts_by_dir.values():
        if artifact_dir_key(candidate.artifact_dir) == target:
            return candidate
    return None


def _generation_members(
    index: WaitDependencyIndex,
    root: ArtifactCandidate,
) -> list[ArtifactCandidate]:
    session_name = root.agent_session_name or root.name
    candidates = list(index.agent_sessions.get(session_name) or ())
    root_key = artifact_dir_key(root.artifact_dir)
    root_in_candidates = any(
        artifact_dir_key(member.artifact_dir) == root_key for member in candidates
    )
    if not root_in_candidates:
        candidates = [root, *candidates]
    else:
        root = next(
            member
            for member in candidates
            if artifact_dir_key(member.artifact_dir) == root_key
        )
    generation = [root]
    timestamps = {root.timestamp}
    remaining = [member for member in candidates if member.timestamp != root.timestamp]
    while remaining:
        attached = [
            member for member in remaining if member.parent_timestamp in timestamps
        ]
        if not attached:
            break
        generation.extend(attached)
        timestamps.update(member.timestamp for member in attached)
        attached_ts = {member.timestamp for member in attached}
        remaining = [
            member for member in remaining if member.timestamp not in attached_ts
        ]
    return generation


__all__ = [
    "WaitTargetBinding",
    "bind_explicit_wait_targets",
    "bind_wait_target",
]
