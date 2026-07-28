"""Pure tribe-wait binding over an already-loaded member snapshot."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sase.core import agent_tribe

TribeWaitBindingState = Literal["reserved", "pending", "bound"]
TribeWaitEntityKind = Literal["agent", "clan"]


@dataclass(frozen=True, slots=True)
class TribeMemberRow:
    """One entity member from an artifact index or display snapshot.

    ``tribe`` is the member's direct tribe assignment.  A caller that has more
    than one direct assignment for the same identity may emit one otherwise
    identical row per assignment.  ``effective_clan_tribe`` is the resolved
    generation-level assignment, when the caller already has one.
    """

    tribe: str | None
    launch_timestamp: str
    identity: str
    name: str
    clan_name: str | None = None
    clan_generation: str | None = None
    effective_clan_tribe: str | None = None
    is_complete: bool = False
    is_terminal: bool = False


@dataclass(frozen=True, slots=True)
class TribeWaitBinding:
    """The current binding classification for one ``%wait(@tribe)`` target."""

    tribe: str
    state: TribeWaitBindingState
    kind: TribeWaitEntityKind | None = None
    identity: str | None = None
    name: str | None = None
    generation: str | None = None
    timestamp: str | None = None
    is_terminal: bool = False


@dataclass(frozen=True, slots=True)
class _EntityCandidate:
    kind: TribeWaitEntityKind
    identity: str | None
    name: str
    generation: str | None
    timestamp: str
    is_complete: bool
    is_terminal: bool

    @property
    def ordering_key(self) -> tuple[str, str, str, str]:
        return (
            self.timestamp,
            self.kind,
            self.name,
            self.generation or "",
        )


def resolve_tribe_wait_binding(
    tribe: str,
    rows: Iterable[TribeMemberRow],
    *,
    newer_than: str | None,
    exclude_identity: str | None = None,
) -> TribeWaitBinding:
    """Resolve the next qualifying entity for *tribe* from *rows*.

    Clan membership is aggregated by ``(clan_name, clan_generation)``.  A
    direct assignment on any member enrolls the whole generation, as does an
    effective generation-level assignment.  The function performs no I/O and
    is safe for callers that already hold an artifact or display snapshot.
    """

    if agent_tribe.is_reserved_tribe_name(tribe):
        return TribeWaitBinding(tribe=tribe, state="reserved")
    if newer_than is None:
        return TribeWaitBinding(tribe=tribe, state="pending")

    snapshot = tuple(rows)
    rows_by_identity: dict[str, TribeMemberRow] = {}
    direct_tribes_by_identity: dict[str, set[str]] = {}
    effective_clan_tribes: dict[tuple[str, str], set[str]] = {}
    clan_member_identities: dict[tuple[str, str], set[str]] = {}

    for row in snapshot:
        rows_by_identity.setdefault(row.identity, row)
        if row.tribe is not None:
            direct_tribes_by_identity.setdefault(row.identity, set()).add(row.tribe)
        clan_key = _clan_key(row)
        if clan_key is None:
            continue
        clan_member_identities.setdefault(clan_key, set()).add(row.identity)
        if row.effective_clan_tribe is not None:
            effective_clan_tribes.setdefault(clan_key, set()).add(
                row.effective_clan_tribe
            )

    enrolled_clans = {
        clan_key
        for clan_key, member_identities in clan_member_identities.items()
        if tribe in effective_clan_tribes.get(clan_key, set())
        or any(
            tribe in direct_tribes_by_identity.get(identity, set())
            for identity in member_identities
        )
    }

    candidates: list[_EntityCandidate] = []
    for identity, row in rows_by_identity.items():
        if _clan_key(row) is not None:
            continue
        if tribe not in direct_tribes_by_identity.get(identity, set()):
            continue
        if identity == exclude_identity or row.launch_timestamp <= newer_than:
            continue
        candidates.append(
            _EntityCandidate(
                kind="agent",
                identity=identity,
                name=row.name,
                generation=None,
                timestamp=row.launch_timestamp,
                is_complete=row.is_complete,
                is_terminal=row.is_terminal,
            )
        )

    for clan_name, generation in enrolled_clans:
        identities = clan_member_identities[(clan_name, generation)]
        members = [rows_by_identity[identity] for identity in identities]
        if not members or exclude_identity in identities:
            continue
        launch_timestamp = min(member.launch_timestamp for member in members)
        if launch_timestamp <= newer_than:
            continue
        candidates.append(
            _EntityCandidate(
                kind="clan",
                identity=None,
                name=clan_name,
                generation=generation,
                timestamp=launch_timestamp,
                is_complete=all(member.is_complete for member in members),
                is_terminal=all(member.is_terminal for member in members),
            )
        )

    complete = [candidate for candidate in candidates if candidate.is_complete]
    selected = min(
        complete or candidates, key=lambda row: row.ordering_key, default=None
    )
    if selected is None:
        return TribeWaitBinding(tribe=tribe, state="pending")
    return TribeWaitBinding(
        tribe=tribe,
        state="bound" if complete else "pending",
        kind=selected.kind,
        identity=selected.identity,
        name=selected.name,
        generation=selected.generation,
        timestamp=selected.timestamp,
        is_terminal=selected.is_terminal,
    )


def _clan_key(row: TribeMemberRow) -> tuple[str, str] | None:
    if row.clan_name is None or row.clan_generation is None:
        return None
    return row.clan_name, row.clan_generation


__all__ = [
    "TribeMemberRow",
    "TribeWaitBinding",
    "TribeWaitBindingState",
    "TribeWaitEntityKind",
    "resolve_tribe_wait_binding",
]
