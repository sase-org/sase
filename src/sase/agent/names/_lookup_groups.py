"""Look up agent sessions and clans from artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.names._common import NamedAgent
from sase.agent.names._lookup_artifacts import (
    done_outcome,
    is_success_outcome,
    read_json_dict,
)
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.dismissed_agent_completion import (
    ArchivedAgentCompletion,
    load_archived_agent_completions,
)
from sase.core.agent_identity_facade import (
    AgentSessionNameKind,
    parse_agent_session_name,
)

if TYPE_CHECKING:
    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactGroupSelectionKind,
        AgentArtifactGroupSelectionResultWire,
        AgentArtifactLookupHitWire,
        AgentArtifactLookupResultWire,
        AgentArtifactLookupTargetKind,
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


def _path_key(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _revalidate_lookup_hits(
    lookup: AgentArtifactLookupResultWire,
) -> tuple[AgentArtifactLookupResultWire, dict[str, dict[str, Any]]]:
    """Drop stale index rows and cache metadata for matching artifact paths."""
    valid_hits = []
    metadata: dict[str, dict[str, Any]] = {}
    for hit in lookup.hits:
        try:
            artifact_dir = Path(hit.artifact_dir).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        if meta is None:
            continue
        valid_hits.append(hit)
        metadata[str(artifact_dir)] = meta
    return replace(lookup, hits=tuple(valid_hits)), metadata


def _query_group(
    target_kind: AgentArtifactLookupTargetKind,
    names: tuple[str, ...],
    selection_kind: AgentArtifactGroupSelectionKind,
    *,
    artifact_dir: str | None = None,
) -> tuple[AgentArtifactGroupSelectionResultWire, dict[str, dict[str, Any]]]:
    from sase.core.agent_artifact_group_lookup import (
        require_complete_group,
        select_agent_artifact_group,
    )
    from sase.core.agent_artifact_lookup import lookup_agent_artifacts
    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactGroupSelectionQueryWire,
        AgentArtifactLookupQueryWire,
        AgentArtifactLookupTargetWire,
    )
    from sase.core.paths import sase_projects_dir

    projects_dir = sase_projects_dir()
    query = AgentArtifactLookupQueryWire(
        target=AgentArtifactLookupTargetWire(kind=target_kind, names=names),
        include_hidden=True,
    )
    lookup = lookup_agent_artifacts(
        default_agent_artifact_index_path(), projects_dir, query
    )
    lookup, metadata = _revalidate_lookup_hits(lookup)
    if artifact_dir is not None and not any(
        _path_key(hit.artifact_dir) == _path_key(artifact_dir) for hit in lookup.hits
    ):
        lookup = replace(
            lookup,
            complete=False,
            diagnostic="requested member is not yet in the indexed group",
        )
    selection = AgentArtifactGroupSelectionQueryWire(
        kind=selection_kind,
        names=names,
        artifact_dir=artifact_dir,
    )
    result = select_agent_artifact_group(lookup, selection)
    return require_complete_group(result), metadata


def _query_pointer(
    artifact_dir: str | Path,
) -> tuple[AgentArtifactLookupResultWire, dict[str, dict[str, Any]]]:
    from sase.core.agent_artifact_group_lookup import require_complete_group
    from sase.core.agent_artifact_lookup import lookup_agent_artifacts
    from sase.core.agent_artifact_lookup_wire import (
        AgentArtifactGroupSelectionResultWire,
        AgentArtifactLookupQueryWire,
        AgentArtifactLookupTargetWire,
    )
    from sase.core.paths import sase_projects_dir

    target = _path_key(artifact_dir)
    query = AgentArtifactLookupQueryWire(
        target=AgentArtifactLookupTargetWire(kind="pointers", artifact_dirs=(target,)),
        include_hidden=True,
    )
    lookup = lookup_agent_artifacts(
        default_agent_artifact_index_path(), sase_projects_dir(), query
    )
    require_complete_group(
        AgentArtifactGroupSelectionResultWire(
            availability=lookup.availability,
            complete=lookup.complete,
            source=lookup.source,
            diagnostic=lookup.diagnostic,
        )
    )
    lookup, metadata = _revalidate_lookup_hits(lookup)
    return lookup, metadata


def _session_members_from_selection(
    group: AgentArtifactGroupSelectionResultWire,
    metadata: dict[str, dict[str, Any]],
    base_name: str,
) -> tuple[AgentSessionMember, ...]:
    rows: list[tuple[AgentArtifactLookupHitWire, dict[str, Any], str, str | None]] = []
    for hit in group.members:
        artifact_dir = Path(hit.artifact_dir).expanduser().resolve(strict=False)
        meta = metadata.get(str(artifact_dir))
        if meta is None:
            continue
        name_value = meta.get("name")
        name = name_value if isinstance(name_value, str) else base_name
        rows.append((hit, meta, name, done_outcome(artifact_dir)))

    archived = load_archived_agent_completions(
        (Path(hit.artifact_dir), meta, hit.project_name)
        for hit, meta, _name, outcome in rows
        if outcome is None and not (Path(hit.artifact_dir) / "done.json").exists()
    )
    return tuple(
        AgentSessionMember(
            name=name,
            artifacts_dir=Path(hit.artifact_dir),
            timestamp=hit.timestamp,
            outcome=(
                outcome
                if outcome is not None
                else archived[str(Path(hit.artifact_dir))].outcome
                if str(Path(hit.artifact_dir)) in archived
                else None
            ),
            parent_timestamp=hit.parent_timestamp,
            archived_completion=archived.get(str(Path(hit.artifact_dir))),
        )
        for hit, _meta, name, outcome in rows
    )


def _clan_members_from_selection(
    group: AgentArtifactGroupSelectionResultWire,
    metadata: dict[str, dict[str, Any]],
) -> tuple[AgentClanMember, ...]:
    rows: list[tuple[AgentArtifactLookupHitWire, dict[str, Any], str, str | None]] = []
    for hit in group.members:
        artifact_dir = Path(hit.artifact_dir).expanduser().resolve(strict=False)
        meta = metadata.get(str(artifact_dir))
        if meta is None:
            continue
        name = meta.get("name")
        if not isinstance(name, str) or not name:
            continue
        rows.append((hit, meta, name, done_outcome(artifact_dir)))

    archived = load_archived_agent_completions(
        (Path(hit.artifact_dir), meta, hit.project_name)
        for hit, meta, _name, outcome in rows
        if outcome is None and not (Path(hit.artifact_dir) / "done.json").exists()
    )
    generation = group.generation or ""
    return tuple(
        AgentClanMember(
            name=name,
            artifacts_dir=Path(hit.artifact_dir),
            timestamp=hit.timestamp,
            outcome=(
                outcome
                if outcome is not None
                else archived[str(Path(hit.artifact_dir))].outcome
                if str(Path(hit.artifact_dir)) in archived
                else None
            ),
            generation=generation,
            archived_completion=archived.get(str(Path(hit.artifact_dir))),
        )
        for hit, _meta, name, outcome in rows
    )


def find_agent_clan(clan_name: str) -> AgentClan | None:
    """Return the newest known generation of *clan_name*."""
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    names = current_owner_agent_name_lookup_candidates(clan_name)
    group, metadata = _query_group("clan", names, "clan_latest")
    if not group.members:
        return None
    selected_name = group.selected_name or clan_name
    return AgentClan(
        name=selected_name,
        generation=group.generation or "",
        members=_clan_members_from_selection(group, metadata),
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

    if not base_name or _is_canonical_agent_session_member_name(base_name):
        return None
    names = current_owner_agent_name_lookup_candidates(base_name)
    group, metadata = _query_group("session", names, "session_latest")
    return _session_from_group(group, metadata, group.selected_name or base_name)


def _session_from_group(
    group: AgentArtifactGroupSelectionResultWire,
    metadata: dict[str, dict[str, Any]],
    base_name: str,
) -> AgentSession | None:
    members = _session_members_from_selection(group, metadata, base_name)
    if not members:
        return None
    root = None
    if group.root is not None:
        root_path = _path_key(group.root.artifact_dir)
        root = next(
            (
                member
                for member in members
                if _path_key(member.artifacts_dir) == root_path
            ),
            None,
        )
    return AgentSession(base_name=base_name, root=root, members=members)


def find_agent_session_by_root_artifact_dir(
    root_artifact_dir: str | Path,
) -> AgentSession | None:
    """Return the session generation owned by this exact root artifact."""
    lookup, _pointer_metadata = _query_pointer(root_artifact_dir)
    if not lookup.hits:
        return None
    pointer = lookup.hits[0]
    base_name = pointer.lookup_session
    if not base_name:
        return None
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    group, metadata = _query_group(
        "session",
        current_owner_agent_name_lookup_candidates(base_name),
        "session_root",
        artifact_dir=pointer.artifact_dir,
    )
    if group.root is None:
        return None
    return _session_from_group(group, metadata, group.selected_name or base_name)


def find_agent_session_by_member_artifact_dir(
    member_artifact_dir: str | Path,
) -> tuple[AgentSession, AgentSessionMember] | None:
    """Find the generation and exact member containing this artifact."""
    lookup, _pointer_metadata = _query_pointer(member_artifact_dir)
    if not lookup.hits:
        return None
    pointer = lookup.hits[0]
    base_name = pointer.lookup_session
    if not base_name:
        return None
    from sase.core.agent_identity_facade import (
        current_owner_agent_name_lookup_candidates,
    )

    group, metadata = _query_group(
        "session",
        current_owner_agent_name_lookup_candidates(base_name),
        "session_member",
        artifact_dir=pointer.artifact_dir,
    )
    generation = _session_from_group(group, metadata, group.selected_name or base_name)
    if generation is None or group.member is None:
        return None
    member_path = _path_key(group.member.artifact_dir)
    member = next(
        (
            item
            for item in generation.members
            if _path_key(item.artifacts_dir) == member_path
        ),
        None,
    )
    return None if member is None else (generation, member)


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
