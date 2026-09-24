"""Look up agent sessions and clans from artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._common import NamedAgent
from sase.agent.names._lookup_artifacts import (
    done_outcome,
    is_success_outcome,
    iter_ace_run_artifact_dirs,
    meta_parent_timestamp,
    read_json_dict,
)
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.dismissed_agent_completion import (
    ArchivedAgentCompletion,
    load_archived_agent_completions,
)
from sase.core.agent_identity_facade import (
    AgentSessionNameKind,
    parse_agent_session_name,
)
from sase.plan_chain import (
    agent_session_base,
    agent_session_parallel_value,
    agent_session_value,
    is_agent_session_member,
    is_plan_chain_artifact_meta,
)


@dataclass(frozen=True)
class AgentSessionMember:
    """One artifact member of a plan-chain agent session."""

    name: str
    artifacts_dir: Path
    timestamp: str
    outcome: str | None
    parent_timestamp: str | None
    archived_completion: ArchivedAgentCompletion | None = None

    @property
    def is_done(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class AgentSession:
    """Newest known generation of a plan-chain agent session."""

    base_name: str
    root: AgentSessionMember | None
    members: tuple[AgentSessionMember, ...]

    @property
    def timestamp(self) -> str:
        if self.root is not None:
            return self.root.timestamp
        return max((member.timestamp for member in self.members), default="")

    @property
    def newest_member_timestamp(self) -> str:
        return max(
            (member.timestamp for member in self.members), default=self.timestamp
        )


@dataclass(frozen=True)
class AgentClanMember:
    """One artifact member of an agent clan."""

    name: str
    artifacts_dir: Path
    timestamp: str
    outcome: str | None
    generation: str
    archived_completion: ArchivedAgentCompletion | None = None

    @property
    def is_done(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class AgentClan:
    """Newest known generation of a rootless agent clan."""

    name: str
    generation: str
    members: tuple[AgentClanMember, ...]

    @property
    def newest_member_timestamp(self) -> str:
        return max((member.timestamp for member in self.members), default="")

    @property
    def is_complete(self) -> bool:
        return bool(self.members) and all(
            is_success_outcome(member.outcome) for member in self.members
        )


def _agent_session_base_from_meta(meta: dict[str, Any]) -> str | None:
    agent_session = agent_session_value(meta)
    if isinstance(agent_session, str) and agent_session:
        return agent_session

    workflow_name = meta.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return None

    if is_plan_chain_artifact_meta(meta):
        return workflow_name

    name = meta.get("name")
    if isinstance(name, str) and agent_session_base(name) == workflow_name:
        return workflow_name

    return None


def _iter_agent_session_members(base_name: str) -> list[AgentSessionMember]:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    base_key = current_owner_agent_name_key(base_name)
    rows: list[tuple[Path, dict[str, Any], str, str | None, str | None]] = []
    for artifact_dir in iter_ace_run_artifact_dirs():
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        agent_session_base_name = (
            None if meta is None else _agent_session_base_from_meta(meta)
        )
        if (
            meta is None
            or agent_session_base_name is None
            or current_owner_agent_name_key(agent_session_base_name) != base_key
        ):
            continue

        name_value = meta.get("name")
        name = name_value if isinstance(name_value, str) else base_name
        rows.append(
            (
                artifact_dir,
                meta,
                name,
                done_outcome(artifact_dir),
                meta_parent_timestamp(meta),
            )
        )

    archived = load_archived_agent_completions(
        (
            artifact_dir,
            meta,
            _project_name_from_artifact_dir(artifact_dir),
        )
        for artifact_dir, meta, _name, outcome, _parent in rows
        if outcome is None and not (artifact_dir / "done.json").exists()
    )
    return [
        AgentSessionMember(
            name=name,
            artifacts_dir=artifact_dir,
            timestamp=artifact_dir.name,
            outcome=(
                outcome
                if outcome is not None
                else archived[str(artifact_dir)].outcome
                if str(artifact_dir) in archived
                else None
            ),
            parent_timestamp=parent_timestamp,
            archived_completion=archived.get(str(artifact_dir)),
        )
        for artifact_dir, _meta, name, outcome, parent_timestamp in rows
    ]


def _project_name_from_artifact_dir(artifact_dir: Path) -> str:
    try:
        info = parse_agent_artifact_path(artifact_dir)
    except (OSError, RuntimeError, ValueError):
        return ""
    return info.project_name if info is not None else ""


def _clan_identity_from_meta(
    meta: dict[str, Any], artifact_dir: Path
) -> tuple[str, str] | None:
    clan = meta.get("agent_clan")
    legacy_parallel = agent_session_parallel_value(meta) is True
    if not isinstance(clan, str) or not clan:
        legacy_agent_session = agent_session_value(meta)
        if (
            not legacy_parallel
            or not isinstance(legacy_agent_session, str)
            or not legacy_agent_session
        ):
            return None
        clan = legacy_agent_session

    generation = meta.get("agent_clan_generation")
    if not isinstance(generation, str) or not generation:
        parent_timestamp = meta_parent_timestamp(meta)
        generation = parent_timestamp or artifact_dir.name
    return clan, generation


def _iter_clan_members(clan_name: str) -> list[AgentClanMember]:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    clan_key = current_owner_agent_name_key(clan_name)
    rows: list[tuple[Path, dict[str, Any], str, str | None, str]] = []
    for artifact_dir in iter_ace_run_artifact_dirs():
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        if meta is None:
            continue
        identity = _clan_identity_from_meta(meta, artifact_dir)
        if identity is None or current_owner_agent_name_key(identity[0]) != clan_key:
            continue
        name = meta.get("name")
        if not isinstance(name, str) or not name:
            continue
        rows.append(
            (
                artifact_dir,
                meta,
                name,
                done_outcome(artifact_dir),
                identity[1],
            )
        )

    archived = load_archived_agent_completions(
        (
            artifact_dir,
            meta,
            _project_name_from_artifact_dir(artifact_dir),
        )
        for artifact_dir, meta, _name, outcome, _generation in rows
        if outcome is None and not (artifact_dir / "done.json").exists()
    )
    return [
        AgentClanMember(
            name=name,
            artifacts_dir=artifact_dir,
            timestamp=artifact_dir.name,
            outcome=(
                outcome
                if outcome is not None
                else archived[str(artifact_dir)].outcome
                if str(artifact_dir) in archived
                else None
            ),
            generation=generation,
            archived_completion=archived.get(str(artifact_dir)),
        )
        for artifact_dir, _meta, name, outcome, generation in rows
    ]


def find_agent_clan(clan_name: str) -> AgentClan | None:
    """Return the newest known generation of *clan_name*."""
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    for candidate in current_owner_agent_name_lookup_candidates(clan_name):
        if (clan := _find_agent_clan_exact(candidate)) is not None:
            return clan
    return None


def _find_agent_clan_exact(clan_name: str) -> AgentClan | None:
    """Return one exact durable clan spelling."""
    members = _iter_clan_members(clan_name)
    if not members:
        return None
    generation = max(member.generation for member in members)
    generation_members = tuple(
        sorted(
            (member for member in members if member.generation == generation),
            key=lambda member: member.timestamp,
        )
    )
    return AgentClan(
        name=clan_name,
        generation=generation,
        members=generation_members,
    )


def is_agent_clan_complete(clan_name: str) -> bool | None:
    """Return whether every member of the newest clan generation completed."""
    clan = find_agent_clan(clan_name)
    return None if clan is None else clan.is_complete


def most_recent_completed_clan_member(clan_name: str) -> NamedAgent | None:
    """Return the newest successful member once the whole clan is complete."""
    clan = find_agent_clan(clan_name)
    if clan is None or not clan.is_complete:
        return None
    member = max(clan.members, key=lambda item: item.timestamp)
    return NamedAgent(
        name=member.name,
        artifacts_dir=str(member.artifacts_dir),
        is_done=True,
        outcome=member.outcome,
    )


def find_agent_session(base_name: str) -> AgentSession | None:
    """Return the newest known generation for *base_name*.

    Only plan-chain/agent-session metadata is considered. Plain exact agents
    named ``base_name`` are intentionally excluded so legacy exact-name lookups
    keep their existing behavior when no agent-session members exist.
    """
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    for candidate in current_owner_agent_name_lookup_candidates(base_name):
        if (agent_session := _find_agent_session_exact(candidate)) is not None:
            return agent_session
    return None


def _find_agent_session_exact(base_name: str) -> AgentSession | None:
    """Return one exact durable agent-session spelling."""
    if not base_name or _is_canonical_agent_session_member_name(base_name):
        return None

    members = _iter_agent_session_members(base_name)
    if not members:
        return None

    roots = [member for member in members if member.parent_timestamp is None]
    if roots:
        root = max(roots, key=lambda member: member.timestamp)
        generation_members = [root]
        generation_timestamps = {root.timestamp}
        remaining = [member for member in members if member is not root]
        while remaining:
            attached = [
                member
                for member in remaining
                if member.parent_timestamp in generation_timestamps
            ]
            if not attached:
                break
            generation_members.extend(attached)
            generation_timestamps.update(member.timestamp for member in attached)
            remaining = [member for member in remaining if member not in attached]
        generation = tuple(
            sorted(generation_members, key=lambda member: member.timestamp)
        )
        return AgentSession(base_name=base_name, root=root, members=generation)

    # Legacy recovery path: if only child artifacts remain, treat all known
    # agent-session members as one generation and let timestamp ordering choose
    # the newest completed handoff member.
    return AgentSession(
        base_name=base_name,
        root=None,
        members=tuple(sorted(members, key=lambda member: member.timestamp)),
    )


def _is_canonical_agent_session_member_name(name: str) -> bool:
    try:
        return parse_agent_session_name(name).kind is AgentSessionNameKind.MEMBER
    except (RuntimeError, ValueError):
        return False


def is_agent_session_complete(base_name: str) -> bool | None:
    """Return whether the newest *base_name* agent-session generation completed."""
    agent_session = find_agent_session(base_name)
    if agent_session is None:
        return None
    if not agent_session.members:
        return False
    return all(is_success_outcome(member.outcome) for member in agent_session.members)


def most_recent_completed_agent_session_member(base_name: str) -> NamedAgent | None:
    """Return the newest successful member of the newest *base_name* session."""
    agent_session = find_agent_session(base_name)
    if agent_session is None:
        return None

    completed = [
        member for member in agent_session.members if is_success_outcome(member.outcome)
    ]
    if not completed:
        return None

    member = max(completed, key=lambda item: item.timestamp)
    return NamedAgent(
        name=member.name,
        artifacts_dir=str(member.artifacts_dir),
        is_done=True,
        outcome=member.outcome,
    )
