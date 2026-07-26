"""Read-only, kind-aware agent catalog for editor completion clients."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sase.agent.status_buckets import aggregate_agent_group_status


@dataclass(frozen=True)
class _CatalogMember:
    name: str
    artifact_dir: str
    timestamp: str
    parent_timestamp: str | None
    family: str | None
    clan: str | None
    clan_generation: str | None
    clan_tribe: str | None
    tribe: str | None
    status: str


def agent_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    """Return a fresh, de-duplicated catalog of prompt reference targets."""
    if request.get("schema_version") != 1:
        raise ValueError("unsupported agent-catalog schema_version")

    from sase.agent.running_listing import list_all_agents
    from sase.project_display_names import project_display_name_for

    agents = list_all_agents()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent in agents:
        name = (agent.name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        project = project_display_name_for(agent.project)
        detail = " · ".join(part for part in (agent.status, project) if part)
        entries.append(
            {
                "name": name,
                "status": agent.status,
                "project": project,
                "kind": "agent",
                "member_count": 1,
                "detail": detail,
            }
        )

    # New list results carry the exact artifact snapshot used above. Tests and
    # mixed-version integrations may still provide an ordinary list, which
    # intentionally degrades to the historical flat agent catalog.
    snapshot = getattr(agents, "artifact_snapshot", None)
    if snapshot is not None:
        try:
            entries.extend(_derive_group_entries(snapshot, agents))
        except Exception:
            # Group metadata is additive. A malformed legacy record, tribe file,
            # or unavailable group resolver must never hide real agents.
            pass

    return {
        "schema_version": 1,
        "status": "ok",
        "message": "",
        "entries": entries,
    }


def _derive_group_entries(snapshot: Any, agents: Iterable[Any]) -> list[dict[str, Any]]:
    members = _catalog_members(snapshot, agents)
    families = _family_entries(members)
    clans, clan_members = _clan_entries(members)
    tribes = _tribe_entries(members, clan_members)
    return [*families, *clans, *tribes]


def _catalog_members(snapshot: Any, agents: Iterable[Any]) -> list[_CatalogMember]:
    from sase.core.agent_clan_context import (
        clan_context_by_key,
        clan_context_for,
        effective_clan_attributes,
    )
    from sase.core.agent_tribe import load_raw_agent_tribes
    from sase.plan_chain import agent_family_base

    statuses = {
        agent.artifacts_dir: agent.status
        for agent in agents
        if getattr(agent, "artifacts_dir", None)
    }
    persisted_tribes = load_raw_agent_tribes()
    clan_contexts = clan_context_by_key(getattr(snapshot, "clan_context", ()))
    members: list[_CatalogMember] = []
    for record in snapshot.records:
        meta = record.agent_meta
        if meta is None:
            continue
        name = (meta.name or "").strip()
        if not name:
            continue

        family = (meta.agent_family or "").strip() or agent_family_base(name)
        clan = (meta.agent_clan or "").strip() or None
        if clan is None and meta.agent_family_parallel and meta.agent_family:
            clan = meta.agent_family
        generation = None
        if clan is not None:
            generation = (
                (meta.agent_clan_generation or "").strip()
                or meta.parent_timestamp
                or record.timestamp
            )

        cl_name = (
            meta.cl_name
            or meta.changespec_name
            or (record.done.cl_name if record.done is not None else None)
        )
        persisted_tribe = _persisted_tribe_for_record(
            persisted_tribes,
            cl_name=cl_name,
            timestamp=record.timestamp,
        )
        context = clan_context_for(
            clan_contexts,
            agent_clan=clan,
            agent_clan_generation=meta.agent_clan_generation,
        )
        clan_tribe, _ = effective_clan_attributes(
            declared_tribe=meta.clan_tribe,
            declared_summary=meta.clan_summary,
            context=context,
        )
        members.append(
            _CatalogMember(
                name=name,
                artifact_dir=record.artifact_dir,
                timestamp=record.timestamp,
                parent_timestamp=meta.parent_timestamp,
                family=family,
                clan=clan,
                clan_generation=generation,
                clan_tribe=clan_tribe,
                tribe=persisted_tribe or ((meta.tribe or "").strip() or None),
                status=statuses.get(record.artifact_dir) or _record_status(record),
            )
        )
    return members


def _persisted_tribe_for_record(
    tribes: dict[tuple[str, str, str | None], str],
    *,
    cl_name: str | None,
    timestamp: str,
) -> str | None:
    if not cl_name:
        return None
    return next(
        (
            tribe
            for (_agent_type, stored_cl, suffix), tribe in tribes.items()
            if stored_cl == cl_name and suffix == timestamp
        ),
        None,
    )


def _record_status(record: Any) -> str:
    done = record.done
    if record.has_done_marker and done is not None:
        if done.outcome in {"failed", "epic_launch_failed"}:
            return "FAILED"
        return "DONE"
    from sase.agent.running_listing import active_status_for_record

    return active_status_for_record(record)


def _family_entries(members: list[_CatalogMember]) -> list[dict[str, Any]]:
    grouped: dict[str, list[_CatalogMember]] = {}
    for member in members:
        if member.family:
            grouped.setdefault(member.family, []).append(member)

    entries: list[dict[str, Any]] = []
    for family, known_members in grouped.items():
        generation = _newest_family_generation(known_members)
        if not generation:
            continue
        count = len(generation)
        entries.append(
            {
                "name": family,
                "kind": "family",
                "member_count": count,
                "detail": f"family · {count} {_members_label(count)}",
            }
        )
    return entries


def _newest_family_generation(
    members: list[_CatalogMember],
) -> list[_CatalogMember]:
    roots = [member for member in members if member.parent_timestamp is None]
    if not roots:
        return sorted(members, key=lambda member: member.timestamp)
    root = max(roots, key=lambda member: member.timestamp)
    generation = [root]
    timestamps = {root.timestamp}
    remaining = [member for member in members if member is not root]
    while remaining:
        attached = [
            member for member in remaining if member.parent_timestamp in timestamps
        ]
        if not attached:
            break
        generation.extend(attached)
        timestamps.update(member.timestamp for member in attached)
        remaining = [member for member in remaining if member not in attached]
    return sorted(generation, key=lambda member: member.timestamp)


def _clan_entries(
    members: list[_CatalogMember],
) -> tuple[list[dict[str, Any]], dict[str, list[_CatalogMember]]]:
    grouped: dict[str, list[_CatalogMember]] = {}
    for member in members:
        if member.clan:
            grouped.setdefault(member.clan, []).append(member)

    newest: dict[str, list[_CatalogMember]] = {}
    entries: list[dict[str, Any]] = []
    for clan, known_members in grouped.items():
        generation = max(member.clan_generation or "" for member in known_members)
        generation_members = [
            member
            for member in known_members
            if (member.clan_generation or "") == generation
        ]
        if not generation_members:
            continue
        newest[clan] = generation_members
        count = len(generation_members)
        status = _aggregate_status(member.status for member in generation_members)
        entries.append(
            {
                "name": clan,
                "kind": "clan",
                "member_count": count,
                "status": status,
                "detail": (
                    f"clan · {count} {_members_label(count)}"
                    + (f" · {status}" if status else "")
                ),
            }
        )
    return entries, newest


def _aggregate_status(statuses: Iterable[str]) -> str:
    return aggregate_agent_group_status(statuses) or "RUNNING"


def _tribe_entries(
    members: list[_CatalogMember],
    clans: dict[str, list[_CatalogMember]],
) -> list[dict[str, Any]]:
    tribe_agents: dict[str, set[str]] = {}
    newest_by_name: dict[str, _CatalogMember] = {}
    for member in members:
        previous = newest_by_name.get(member.name)
        if previous is None or member.timestamp > previous.timestamp:
            newest_by_name[member.name] = member
    for member in newest_by_name.values():
        if member.tribe:
            tribe_agents.setdefault(member.tribe, set()).add(member.name)

    tribe_clans: dict[str, set[str]] = {}
    for clan, clan_members in clans.items():
        for tribe in _effective_clan_tribes(clan, clan_members):
            tribe_clans.setdefault(tribe, set()).add(clan)

    ordered_tribes = dict.fromkeys([*tribe_agents, *tribe_clans])
    entries: list[dict[str, Any]] = []
    for tribe in ordered_tribes:
        agent_count = len(tribe_agents.get(tribe, set()))
        clan_count = len(tribe_clans.get(tribe, set()))
        member_count = agent_count + clan_count
        if member_count == 0:
            continue
        detail_parts = ["tribe"]
        if agent_count:
            detail_parts.append(
                f"{agent_count} {'agent' if agent_count == 1 else 'agents'}"
            )
        if clan_count:
            detail_parts.append(
                f"{clan_count} {'clan' if clan_count == 1 else 'clans'}"
            )
        entries.append(
            {
                "name": f"@{tribe}",
                "kind": "tribe",
                "member_count": member_count,
                "detail": " · ".join(detail_parts),
            }
        )
    return entries


def _effective_clan_tribes(
    clan: str,
    members: list[_CatalogMember],
) -> tuple[str, ...]:
    explicit = [member for member in members if member.clan_tribe]
    if explicit:
        try:
            from sase.core.agent_clan_tribe import (
                ClanTribeMemberWire,
                resolve_clan_tribe,
            )

            generation = members[0].clan_generation if members else None
            resolution = resolve_clan_tribe(
                clan,
                generation,
                [
                    ClanTribeMemberWire(
                        agent_clan=clan,
                        agent_clan_generation=member.clan_generation,
                        clan_tribe=member.clan_tribe,
                        launch_timestamp=member.timestamp,
                        identity=f"{member.artifact_dir}:{member.name}",
                    )
                    for member in members
                ],
            )
            return (resolution.tribe,) if resolution.tribe else ()
        except Exception:
            newest = max(explicit, key=lambda member: member.timestamp)
            return (newest.clan_tribe,) if newest.clan_tribe else ()
    return tuple(dict.fromkeys(member.tribe for member in members if member.tribe))


def _members_label(count: int) -> str:
    return "member" if count == 1 else "members"


__all__ = ["agent_catalog_response"]
