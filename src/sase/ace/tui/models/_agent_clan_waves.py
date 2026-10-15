"""Adapt loaded clan rows to Rust dependency waves and TUI presentation views."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from sase.agent.status_buckets import agent_is_asking, agent_status_bucket
from sase.core.agent_clan_waves import (
    ClanWavesWire,
    ClanWaveMemberWire,
    ClanWaveRequestWire,
    project_clan_waves,
)

from .agent import Agent

ClanWaveLabelKind = Literal["number", "seal", "unresolved"]


class _ClanWaveState(StrEnum):
    """Folded state of the loaded rows assigned to one clan wave."""

    FAILED = "failed"
    NEEDS_YOU = "needs_you"
    IN_FLIGHT = "in_flight"
    DONE = "done"
    NOT_STARTED = "not_started"
    DISMISSED_ONLY = "dismissed_only"


@dataclass(frozen=True)
class ClanWaveSlot:
    """Layout placement for one direct clan-member anchor."""

    wave_index: int | None
    label_kind: ClanWaveLabelKind
    number: int | None
    rank: int
    open: bool


@dataclass(frozen=True)
class _ClanWaveView:
    """Container-level view of a numbered, seal, or unresolved stage."""

    number: int | None
    kind: ClanWaveLabelKind
    member_identities: tuple[str, ...]
    ghost_names: tuple[str, ...]
    state: _ClanWaveState
    predecessor_identities: tuple[str, ...]


@dataclass(frozen=True)
class _ClanWaveMemberView:
    """Dependency and external-wait details for one loaded direct member."""

    identity: str
    relative_label: str
    wave_index: int | None
    predecessors: tuple[str, ...]
    ghost_predecessors: tuple[str, ...]
    external_wait_count: int


@dataclass(frozen=True)
class ClanWaveSummary:
    """Memoized layout plus the current projection's folded wave states."""

    layered: bool
    numbered_wave_count: int
    has_seal: bool
    waves: tuple[_ClanWaveView, ...]
    members: tuple[_ClanWaveMemberView, ...]
    unresolved_identities: tuple[str, ...]


@dataclass(frozen=True)
class _SimpleWaveLayout:
    """Cached identity mapping for a dependency-free one-wave clan."""

    identities: tuple[str, ...]
    members: tuple[_ClanWaveMemberView, ...]


def clan_wave_identity_key(agent: Agent) -> str:
    """Match the durable clan-member identity used by clan attribute wires."""
    return (
        f"{agent.agent_type.value}:{agent.cl_name}:"
        f"{agent.raw_suffix or ''}:{agent.agent_name or ''}"
    )


def _launch_key(agent: Agent) -> str:
    """Encode ``ordered_clan_members``' present-time, time, and name order."""
    has_no_start = agent.start_time is None
    timestamp = agent.start_time.isoformat() if agent.start_time else ""
    name = agent.presented_agent_name or agent.display_name
    return f"{int(has_no_start)}:{timestamp}\x1f{name}"


def _canonical_clan_name(
    name: str,
    clan_name: str,
    clan_spellings: tuple[str, ...],
) -> str:
    """Map raw/presented clan spellings and their hoods to one core name."""
    for spelling in clan_spellings:
        if name == spelling:
            return clan_name
        prefix = f"{spelling}."
        if name.startswith(prefix):
            return f"{clan_name}{name[len(spelling) :]}"
    return name


def _member_wires(
    clan_name: str,
    units: list[list[Agent]],
) -> tuple[ClanWaveMemberWire, ...]:
    clan_spellings = {clan_name}
    for unit in units:
        for row in unit:
            if row.agent_clan:
                clan_spellings.add(row.agent_clan)
            presented = row.presented_clan_reference_name()
            if presented:
                clan_spellings.add(presented)
    ordered_spellings = tuple(
        sorted(clan_spellings, key=lambda item: (-len(item), item))
    )
    wire_name_by_suffix = {
        unit[0].raw_suffix: _canonical_clan_name(
            unit[0].presented_identity_name
            or unit[0].agent_name
            or clan_wave_identity_key(unit[0]),
            clan_name,
            ordered_spellings,
        )
        for unit in units
        if unit and unit[0].raw_suffix
    }

    wires: list[ClanWaveMemberWire] = []
    for unit in units:
        if not unit:
            continue
        anchor = unit[0]
        identity = clan_wave_identity_key(anchor)
        wire_name = _canonical_clan_name(
            anchor.presented_identity_name or anchor.agent_name or identity,
            clan_name,
            ordered_spellings,
        )
        aliases = {
            name
            for row in unit
            for name in (row.agent_name, row.presented_identity_name)
            if name
        }
        aliases.add(identity)
        aliases.update(
            _canonical_clan_name(name, clan_name, ordered_spellings)
            for name in tuple(aliases)
        )
        wait_for = {
            _canonical_clan_name(target, clan_name, ordered_spellings)
            for row in unit
            for target in row.waiting_for
            if target
        }
        wait_for_beads = {
            bead_id for row in unit for bead_id in row.waiting_for_beads if bead_id
        }
        wait_for_hoods = {
            _canonical_clan_name(hood, clan_name, ordered_spellings)
            for row in unit
            for hood in row.waiting_for_hoods
            if hood
        }
        retry_root = next(
            (
                row.retry_chain_root_timestamp
                for row in unit
                if row.retry_chain_root_timestamp
            ),
            None,
        )
        phase_bead_id = next(
            (row.phase_bead_id for row in unit if row.phase_bead_id),
            None,
        )
        seal = any(row.epic_bead_id for row in unit) and not any(
            row.phase_bead_id for row in unit
        )
        wires.append(
            ClanWaveMemberWire(
                name=wire_name,
                aliases=tuple(sorted(aliases)),
                launch_key=_launch_key(anchor),
                wait_for=tuple(sorted(wait_for)),
                wait_for_beads=tuple(sorted(wait_for_beads)),
                wait_for_hoods=tuple(sorted(wait_for_hoods)),
                phase_bead_id=phase_bead_id,
                retry_of=wire_name_by_suffix.get(retry_root) if retry_root else None,
                seal=seal,
            )
        )
    return tuple(wires)


def _simple_member_specs(
    units: list[list[Agent]],
) -> tuple[tuple[str, str, str], ...] | None:
    """Return compact wire specs for dependency-free one-row units.

    Aliases and clan spellings only affect edge resolution. When every unit is
    one row and the roster declares no waits, the core needs only each member's
    unique name and launch key to produce the same single wave. The identity is
    carried in aliases so cached layouts invalidate if an artifact identity
    changes while its displayed name stays the same.
    """
    specs: list[tuple[str, str, str]] = []
    for unit in units:
        if len(unit) != 1:
            return None
        row = unit[0]
        if (
            not row.agent_name
            or row.presented_identity_name not in (None, row.agent_name)
            or row.waiting_for
            or row.waiting_for_beads
            or row.waiting_for_hoods
            or row.retry_chain_root_timestamp
            or row.epic_bead_id
        ):
            return None
        specs.append((row.agent_name, _launch_key(row), clan_wave_identity_key(row)))
    return tuple(specs)


@lru_cache(maxsize=16)
def _simple_request(
    clan_name: str,
    specs: tuple[tuple[str, str, str], ...],
) -> ClanWaveRequestWire:
    """Reuse immutable requests for unchanged, dependency-free rosters."""
    return ClanWaveRequestWire(
        clan_name=clan_name,
        members=tuple(
            ClanWaveMemberWire(name=name, launch_key=launch_key, aliases=(identity,))
            for name, launch_key, identity in specs
        ),
    )


@lru_cache(maxsize=16)
def _simple_wave_layout(
    request: ClanWaveRequestWire,
) -> _SimpleWaveLayout | None:
    """Cache the static views for a binding-confirmed single-wave request."""
    wire: ClanWavesWire = project_clan_waves(request)
    if (
        len(wire.waves) != 1
        or wire.seal
        or wire.unresolved
        or wire.ghosts
        or any(predecessors for _, predecessors in wire.preds)
        or any(count for _, count in wire.external_waits)
    ):
        return None
    identity_by_name = {
        member.name: member.aliases[0] for member in request.members if member.aliases
    }
    names = wire.waves[0]
    if len(names) != len(request.members) or set(names) != set(identity_by_name):
        return None
    identities = tuple(identity_by_name[name] for name in names)
    return _SimpleWaveLayout(
        identities=identities,
        members=tuple(
            _ClanWaveMemberView(
                identity=identity_by_name[name],
                relative_label="1",
                wave_index=1,
                predecessors=(),
                ghost_predecessors=(),
                external_wait_count=0,
            )
            for name in names
        ),
    )


@lru_cache(maxsize=32)
def _simple_slots(
    request: ClanWaveRequestWire,
    is_open: bool,
) -> dict[str, ClanWaveSlot]:
    """Reuse immutable slots while a flat clan's single-wave state is stable."""
    layout = _simple_wave_layout(request)
    assert layout is not None
    return {
        identity: ClanWaveSlot(
            wave_index=1,
            label_kind="number",
            number=1,
            rank=rank,
            open=is_open,
        )
        for rank, identity in enumerate(layout.identities)
    }


def _effective_state_bucket(
    agent: Agent,
    status_buckets: dict[int, str] | None,
) -> str:
    bucket = status_buckets.get(id(agent)) if status_buckets is not None else None
    if bucket is None:
        bucket = agent_status_bucket(agent)
    # A terminal failed attempt that has a recorded retry is already handled;
    # it must not turn the retry's wave red.
    if bucket == "Failed" and agent.retried_as_timestamp:
        return "Done"
    return bucket


def _is_finalizing(agent: Agent) -> bool:
    phase = getattr(agent.finalizer_status, "phase", None)
    return agent.status == "FINALIZING" or phase in {"declaring", "executing"}


def _wave_state(
    identities: tuple[str, ...],
    rows_by_identity: dict[str, list[Agent]],
    ghost_names: tuple[str, ...],
    status_buckets: dict[int, str] | None,
) -> tuple[_ClanWaveState, bool]:
    rows = [
        row for identity in identities for row in rows_by_identity.get(identity, ())
    ]
    if not rows:
        return (
            _ClanWaveState.DISMISSED_ONLY
            if ghost_names
            else _ClanWaveState.NOT_STARTED,
            False,
        )

    buckets = [_effective_state_bucket(row, status_buckets) for row in rows]
    unfinished = any(bucket != "Done" for bucket in buckets)
    if any(bucket == "Failed" for bucket in buckets):
        return _ClanWaveState.FAILED, unfinished
    if any(
        bucket == "Stopped" or agent_is_asking(row.status)
        for row, bucket in zip(rows, buckets, strict=True)
    ):
        return _ClanWaveState.NEEDS_YOU, unfinished
    if any(
        bucket in {"Running", "Starting", "Queued"} or _is_finalizing(row)
        for row, bucket in zip(rows, buckets, strict=True)
    ):
        return _ClanWaveState.IN_FLIGHT, unfinished
    if all(bucket == "Done" for bucket in buckets) and not ghost_names:
        return _ClanWaveState.DONE, False
    if all(bucket in {"Waiting", "Done"} for bucket in buckets) and all(
        bucket == "Waiting" for bucket in buckets
    ):
        return _ClanWaveState.NOT_STARTED, True
    # This also covers a Done/Waiting mix and loaded Done members beside a ghost:
    # neither shape is complete, while the loaded work remains actionable.
    return _ClanWaveState.IN_FLIGHT, unfinished


def project_clan_wave_model(
    clan_name: str,
    units: list[list[Agent]],
    *,
    status_buckets: dict[int, str] | None = None,
) -> tuple[ClanWaveSummary, dict[str, ClanWaveSlot]]:
    """Project one clan's direct-member units into layout and state views."""
    simple_specs = _simple_member_specs(units)
    if simple_specs is not None:
        request = _simple_request(clan_name, simple_specs)
        simple_layout = _simple_wave_layout(request)
        # Keep the core memo exercised on each projection; after the first
        # request this is a constant-time facade hit, and the expensive static
        # adapter views remain cached separately from the live state fold.
        project_clan_waves(request)
        if simple_layout is not None:
            rows_by_identity = {
                identity: [unit[0]]
                for identity, unit in zip(
                    (spec[2] for spec in simple_specs), units, strict=True
                )
            }
            state, is_open = _wave_state(
                simple_layout.identities,
                rows_by_identity,
                (),
                status_buckets,
            )
            summary = ClanWaveSummary(
                layered=False,
                numbered_wave_count=1,
                has_seal=False,
                waves=(
                    _ClanWaveView(
                        number=1,
                        kind="number",
                        member_identities=simple_layout.identities,
                        ghost_names=(),
                        state=state,
                        predecessor_identities=(),
                    ),
                ),
                members=simple_layout.members,
                unresolved_identities=(),
            )
            return summary, _simple_slots(request, is_open)

    member_wires = _member_wires(clan_name, units)
    wire = project_clan_waves(ClanWaveRequestWire(clan_name, member_wires))
    rows_by_identity = {clan_wave_identity_key(unit[0]): unit for unit in units if unit}
    identity_by_name = {
        member.name: clan_wave_identity_key(unit[0])
        for member, unit in zip(
            member_wires, (unit for unit in units if unit), strict=True
        )
    }
    wave_of = dict(wire.wave_of)
    preds_by_name = dict(wire.preds)
    external_waits = dict(wire.external_waits)
    ghost_set = set(wire.ghosts)

    numbered_names = [name for wave in wire.waves for name in wave]
    ordered_names = [
        *numbered_names,
        *wire.seal,
        *wire.unresolved,
    ]
    rank_by_name = {
        name: rank for rank, name in enumerate(dict.fromkeys(ordered_names))
    }
    member_names = set(identity_by_name)
    rank_by_identity = {
        identity_by_name[name]: rank
        for name, rank in rank_by_name.items()
        if name in identity_by_name
    }

    def member_identities(names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(identity_by_name[name] for name in names if name in member_names)

    def predecessor_data(name: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        predecessor_names = preds_by_name.get(name, ())
        predecessor_identities = tuple(
            identity_by_name[predecessor]
            for predecessor in predecessor_names
            if predecessor in member_names
        )
        ghost_predecessors = tuple(
            predecessor
            for predecessor in predecessor_names
            if predecessor in ghost_set or predecessor not in member_names
        )
        return predecessor_identities, ghost_predecessors

    wave_views: list[_ClanWaveView] = []
    wave_open_by_name: dict[str, bool] = {}
    wave_index_by_name: dict[str, int | None] = {}
    label_kind_by_name: dict[str, ClanWaveLabelKind] = {}

    for number, names in enumerate(wire.waves, start=1):
        identities = member_identities(names)
        ghosts = tuple(
            name for name in names if name in ghost_set or name not in member_names
        )
        state, is_open = _wave_state(
            identities,
            rows_by_identity,
            ghosts,
            status_buckets,
        )
        predecessor_order = {
            predecessor
            for name in names
            if name in member_names
            for predecessor in predecessor_data(name)[0]
        }
        predecessors = tuple(
            sorted(
                predecessor_order,
                key=lambda identity: rank_by_identity.get(identity, 0),
            )
        )
        wave_views.append(
            _ClanWaveView(
                number=number,
                kind="number",
                member_identities=identities,
                ghost_names=ghosts,
                state=state,
                predecessor_identities=predecessors,
            )
        )
        for name in names:
            if name in member_names:
                wave_open_by_name[name] = is_open
                wave_index_by_name[name] = wave_of.get(name, number)
                label_kind_by_name[name] = "number"

    if wire.seal:
        identities = member_identities(wire.seal)
        state, is_open = _wave_state(
            identities,
            rows_by_identity,
            (),
            status_buckets,
        )
        predecessor_order = {
            predecessor
            for name in wire.seal
            if name in member_names
            for predecessor in predecessor_data(name)[0]
        }
        predecessors = tuple(
            sorted(
                predecessor_order,
                key=lambda identity: rank_by_identity.get(identity, 0),
            )
        )
        wave_views.append(
            _ClanWaveView(
                number=None,
                kind="seal",
                member_identities=identities,
                ghost_names=(),
                state=state,
                predecessor_identities=predecessors,
            )
        )
        for name in wire.seal:
            if name in member_names:
                wave_open_by_name[name] = is_open
                wave_index_by_name[name] = None
                label_kind_by_name[name] = "seal"

    if wire.unresolved:
        identities = member_identities(wire.unresolved)
        state, is_open = _wave_state(
            identities,
            rows_by_identity,
            (),
            status_buckets,
        )
        predecessor_order = {
            predecessor
            for name in wire.unresolved
            if name in member_names
            for predecessor in predecessor_data(name)[0]
        }
        predecessors = tuple(
            sorted(
                predecessor_order,
                key=lambda identity: rank_by_identity.get(identity, 0),
            )
        )
        wave_views.append(
            _ClanWaveView(
                number=None,
                kind="unresolved",
                member_identities=identities,
                ghost_names=(),
                state=state,
                predecessor_identities=predecessors,
            )
        )
        for name in wire.unresolved:
            if name in member_names:
                wave_open_by_name[name] = is_open
                wave_index_by_name[name] = None
                label_kind_by_name[name] = "unresolved"

    slots: dict[str, ClanWaveSlot] = {}
    member_views: list[_ClanWaveMemberView] = []
    for name in dict.fromkeys(ordered_names):
        if name not in member_names:
            continue
        kind = label_kind_by_name.get(name, "unresolved")
        member_number = wave_of.get(name) if kind == "number" else None
        label = (
            str(member_number)
            if member_number is not None
            else ("∎" if kind == "seal" else "?")
        )
        identity = identity_by_name[name]
        wave_index = wave_index_by_name.get(name)
        slots[identity] = ClanWaveSlot(
            wave_index=wave_index,
            label_kind=kind,
            number=member_number,
            rank=rank_by_name[name],
            open=wave_open_by_name.get(name, False),
        )
        predecessors, ghost_predecessors = predecessor_data(name)
        member_views.append(
            _ClanWaveMemberView(
                identity=identity,
                relative_label=label,
                wave_index=wave_index,
                predecessors=tuple(
                    sorted(predecessors, key=lambda item: rank_by_identity.get(item, 0))
                ),
                ghost_predecessors=ghost_predecessors,
                external_wait_count=external_waits.get(name, 0),
            )
        )

    unresolved_identities = member_identities(wire.unresolved)
    numbered_wave_count = len(wire.waves)
    has_seal = bool(wire.seal)
    layered = numbered_wave_count + int(has_seal) >= 2 or bool(unresolved_identities)
    return (
        ClanWaveSummary(
            layered=layered,
            numbered_wave_count=numbered_wave_count,
            has_seal=has_seal,
            waves=tuple(wave_views),
            members=tuple(member_views),
            unresolved_identities=unresolved_identities,
        ),
        slots,
    )


__all__ = [
    "ClanWaveSlot",
    "ClanWaveSummary",
    "clan_wave_identity_key",
    "project_clan_wave_model",
]
