"""Effective hold-target identity from stored and clan-generation evidence.

Selector expansion and candidate membership share this snapshot: load stored
assignments once, resolve each clan generation once, and reuse those facts for
every record in the same admission or display decision. Callers must not scan
artifact history from a TUI render path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sase.core.agent_clan_tribe import ClanTribeMemberWire, resolve_clan_tribe
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.agent_tribe import RawAgentTribeIdentity, load_raw_agent_tribes

_HOLD_IDENTITY_SCRATCH_KEYS = (
    "hold_cl_name",
    "hold_clan_generation",
    "hold_meta_tribe",
    "hold_clan_tribe",
)


def _stored_hold_assignments() -> dict[RawAgentTribeIdentity, str]:
    """Return the host assignment store without scanning artifact history."""
    return load_raw_agent_tribes()


def _posthoc_hold_tribe(
    assignments: Mapping[RawAgentTribeIdentity, str],
    *,
    cl_name: str | None,
    timestamp: str | None,
) -> str | None:
    """Return a stored posthoc assignment for one launch identity."""
    if not cl_name or not timestamp:
        return None
    for agent_type in ("workflow", "run"):
        tribe = assignments.get((agent_type, cl_name, timestamp))
        if tribe:
            return tribe
    return None


def _hold_clan_generation(
    *,
    clan_generation: str | None,
    parent_timestamp: str | None,
    timestamp: str | None,
) -> str | None:
    """Return the wait-index generation key for one clan member."""
    for value in (clan_generation, parent_timestamp, timestamp):
        if isinstance(value, str) and value:
            return value
    return None


def hold_membership_tribes(
    *,
    direct: Iterable[str | None] = (),
    effective_clan: str | None = None,
) -> tuple[str, ...]:
    """Return unique tribe membership for one hold candidate."""
    values = [value for value in direct if isinstance(value, str) and value]
    if isinstance(effective_clan, str) and effective_clan:
        values.append(effective_clan)
    return tuple(sorted(set(values)))


def primary_hold_tribe(
    membership: Sequence[str],
    *,
    preferred: Iterable[str | None] = (),
) -> str | None:
    """Return the preferred membership tribe, else the first sorted member."""
    membership_set = set(membership)
    for value in preferred:
        if isinstance(value, str) and value in membership_set:
            return value
    return membership[0] if membership else None


def apply_hold_identity_to_capacity_records(
    records: Sequence[dict[str, Any]],
    *,
    scan_records: Sequence[AgentArtifactRecordWire] | None = None,
    stored_assignments: Mapping[RawAgentTribeIdentity, str] | None = None,
) -> None:
    """Overlay posthoc and clan-generation tribes onto capacity records.

    Mutates *records* in place. Scratch identity keys are left in place for
    the caller to strip before the Rust capacity wire.
    """
    if not records:
        return
    assignments = (
        dict(stored_assignments)
        if stored_assignments is not None
        else _stored_hold_assignments()
    )
    scan_by_dir = {record.artifact_dir: record for record in (scan_records or ())}
    for record in records:
        _attach_hold_identity_scratch(
            record, scan_by_dir.get(str(record.get("artifact_dir") or ""))
        )
    clan_members: dict[tuple[str, str], list[ClanTribeMemberWire]] = {}
    for record in records:
        clan = record.get("clan")
        generation = record.get("hold_clan_generation")
        if not isinstance(clan, str) or not clan:
            continue
        if not isinstance(generation, str) or not generation:
            continue
        artifact_dir = str(record.get("artifact_dir") or "")
        timestamp = str(record.get("timestamp") or "")
        clan_tribe = record.get("hold_clan_tribe")
        clan_members.setdefault((clan, generation), []).append(
            ClanTribeMemberWire(
                agent_clan=clan,
                agent_clan_generation=generation,
                launch_timestamp=timestamp,
                identity=artifact_dir or timestamp,
                clan_tribe=clan_tribe if isinstance(clan_tribe, str) else None,
            )
        )
    effective_clans: dict[tuple[str, str], str] = {}
    for (clan, generation), members in clan_members.items():
        tribe = resolve_clan_tribe(clan, generation, members).tribe
        if tribe:
            effective_clans[(clan, generation)] = tribe
    for record in records:
        cl_name = record.get("hold_cl_name")
        launch_timestamp = record.get("timestamp")
        posthoc = _posthoc_hold_tribe(
            assignments,
            cl_name=cl_name if isinstance(cl_name, str) else None,
            timestamp=launch_timestamp if isinstance(launch_timestamp, str) else None,
        )
        meta_tribe = record.get("hold_meta_tribe")
        generation = record.get("hold_clan_generation")
        clan = record.get("clan")
        effective = None
        if isinstance(clan, str) and isinstance(generation, str):
            effective = effective_clans.get((clan, generation))
        membership = hold_membership_tribes(
            direct=(posthoc, meta_tribe if isinstance(meta_tribe, str) else None),
            effective_clan=effective,
        )
        if not membership:
            fallback = record.get("hold_clan_tribe")
            if isinstance(fallback, str) and fallback:
                membership = (fallback,)
        record["tribes"] = list(membership)
        record["tribe"] = primary_hold_tribe(
            membership,
            preferred=(
                posthoc,
                meta_tribe if isinstance(meta_tribe, str) else None,
                effective,
                record.get("hold_clan_tribe")
                if isinstance(record.get("hold_clan_tribe"), str)
                else None,
            ),
        )


def strip_hold_identity_scratch_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Remove overlay scratch keys that the Rust capacity wire rejects."""
    for key in _HOLD_IDENTITY_SCRATCH_KEYS:
        record.pop(key, None)
    return record


def attach_hold_identity_scratch_from_meta(
    record: dict[str, Any],
    *,
    cl_name: str | None = None,
    clan_generation: str | None = None,
    parent_timestamp: str | None = None,
    timestamp: str | None = None,
    meta_tribe: str | None = None,
    clan_tribe: str | None = None,
    clan: str | None = None,
) -> None:
    """Record the identity ingredients overlay needs, without collapsing them."""
    record["hold_cl_name"] = (
        cl_name or record.get("hold_cl_name") or record.get("cl_name")
    )
    record["hold_meta_tribe"] = (
        meta_tribe if meta_tribe is not None else record.get("hold_meta_tribe")
    )
    record["hold_clan_tribe"] = (
        clan_tribe if clan_tribe is not None else record.get("hold_clan_tribe")
    )
    record["hold_clan_generation"] = _hold_clan_generation(
        clan_generation=clan_generation
        or (
            record.get("hold_clan_generation")
            if isinstance(record.get("hold_clan_generation"), str)
            else None
        ),
        parent_timestamp=parent_timestamp
        or (
            record.get("parent_timestamp")
            if isinstance(record.get("parent_timestamp"), str)
            else None
        ),
        timestamp=timestamp
        or (
            record.get("timestamp")
            if isinstance(record.get("timestamp"), str)
            else None
        ),
    )
    if clan and not record.get("clan"):
        record["clan"] = clan


def _attach_hold_identity_scratch(
    record: dict[str, Any],
    scan: AgentArtifactRecordWire | None,
) -> None:
    if scan is not None:
        meta = scan.agent_meta
        attach_hold_identity_scratch_from_meta(
            record,
            cl_name=None if meta is None else meta.cl_name,
            clan_generation=None if meta is None else meta.agent_clan_generation,
            parent_timestamp=None if meta is None else meta.parent_timestamp,
            timestamp=scan.timestamp,
            meta_tribe=None if meta is None else meta.tribe,
            clan_tribe=None if meta is None else meta.clan_tribe,
            clan=None if meta is None else meta.agent_clan,
        )
        return
    attach_hold_identity_scratch_from_meta(record)


__all__ = [
    "apply_hold_identity_to_capacity_records",
    "attach_hold_identity_scratch_from_meta",
    "hold_membership_tribes",
    "primary_hold_tribe",
    "strip_hold_identity_scratch_fields",
]
