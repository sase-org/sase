"""Look up agent families and clans from artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names._common import NamedAgent
from sase.agent.names._lookup_artifacts import (
    SUCCESS_OUTCOME,
    done_outcome,
    iter_ace_run_artifact_dirs,
    meta_parent_timestamp,
    read_json_dict,
)
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.dismissed_agent_completion import (
    ArchivedAgentCompletion,
    load_archived_agent_completions,
)
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    agent_family_base,
    is_agent_family_member,
    is_plan_chain_artifact_meta,
)


@dataclass(frozen=True)
class AgentFamilyMember:
    """One artifact member of a plan-chain agent family."""

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
class AgentFamily:
    """Newest known generation of a plan-chain agent family."""

    base_name: str
    root: AgentFamilyMember | None
    members: tuple[AgentFamilyMember, ...]

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
            member.outcome == SUCCESS_OUTCOME for member in self.members
        )


def _family_base_from_meta(meta: dict[str, Any]) -> str | None:
    family = meta.get(AGENT_FAMILY_FIELD)
    if isinstance(family, str) and family:
        return family

    workflow_name = meta.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return None

    if is_plan_chain_artifact_meta(meta):
        return workflow_name

    name = meta.get("name")
    if isinstance(name, str) and agent_family_base(name) == workflow_name:
        return workflow_name

    return None


def _iter_family_members(base_name: str) -> list[AgentFamilyMember]:
    from sase.core.machine_hood_facade import canonical_local_agent_name_key

    base_key = canonical_local_agent_name_key(base_name)
    rows: list[tuple[Path, dict[str, Any], str, str | None, str | None]] = []
    for artifact_dir in iter_ace_run_artifact_dirs():
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        family_base = None if meta is None else _family_base_from_meta(meta)
        if (
            meta is None
            or family_base is None
            or canonical_local_agent_name_key(family_base) != base_key
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
        AgentFamilyMember(
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
    legacy_parallel = meta.get("agent_family_parallel") is True
    if not isinstance(clan, str) or not clan:
        legacy_family = meta.get(AGENT_FAMILY_FIELD)
        if (
            not legacy_parallel
            or not isinstance(legacy_family, str)
            or not legacy_family
        ):
            return None
        clan = legacy_family

    generation = meta.get("agent_clan_generation")
    if not isinstance(generation, str) or not generation:
        parent_timestamp = meta_parent_timestamp(meta)
        generation = parent_timestamp or artifact_dir.name
    return clan, generation


def _iter_clan_members(clan_name: str) -> list[AgentClanMember]:
    from sase.core.machine_hood_facade import canonical_local_agent_name_key

    clan_key = canonical_local_agent_name_key(clan_name)
    rows: list[tuple[Path, dict[str, Any], str, str | None, str]] = []
    for artifact_dir in iter_ace_run_artifact_dirs():
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        if meta is None:
            continue
        identity = _clan_identity_from_meta(meta, artifact_dir)
        if identity is None or canonical_local_agent_name_key(identity[0]) != clan_key:
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
    from sase.core.machine_hood_facade import local_agent_name_lookup_candidates

    for candidate in local_agent_name_lookup_candidates(clan_name):
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


def find_agent_family(base_name: str) -> AgentFamily | None:
    """Return the newest known generation for *base_name*.

    Only plan-chain/family metadata is considered. Plain exact agents named
    ``base_name`` are intentionally excluded so legacy exact-name lookups keep
    their existing behavior when no family members exist.
    """
    from sase.core.machine_hood_facade import local_agent_name_lookup_candidates

    for candidate in local_agent_name_lookup_candidates(base_name):
        if (family := _find_agent_family_exact(candidate)) is not None:
            return family
    return None


def _find_agent_family_exact(base_name: str) -> AgentFamily | None:
    """Return one exact durable family spelling."""
    if not base_name or is_agent_family_member(base_name):
        return None

    members = _iter_family_members(base_name)
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
        return AgentFamily(base_name=base_name, root=root, members=generation)

    # Legacy recovery path: if only child artifacts remain, treat all known
    # family members as one generation and let timestamp ordering choose the
    # newest completed handoff member.
    return AgentFamily(
        base_name=base_name,
        root=None,
        members=tuple(sorted(members, key=lambda member: member.timestamp)),
    )


def is_agent_family_complete(base_name: str) -> bool | None:
    """Return whether the newest *base_name* family generation completed."""
    family = find_agent_family(base_name)
    if family is None:
        return None
    if not family.members:
        return False
    return all(member.outcome == SUCCESS_OUTCOME for member in family.members)


def most_recent_completed_family_member(base_name: str) -> NamedAgent | None:
    """Return the newest successful member of the newest *base_name* family."""
    family = find_agent_family(base_name)
    if family is None:
        return None

    completed = [
        member for member in family.members if member.outcome == SUCCESS_OUTCOME
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
