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
    ranks: tuple[tuple[str, int], ...]
    members: tuple[_ClanWaveMemberView, ...]
    wave_index: int
    wave_number: int | None
    layered: bool
    numbered_wave_count: int
    has_seal: bool


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


def _clan_names(clan_name: str, units: list[list[Agent]]) -> tuple[str, ...]:
    """Keep raw and presented clan spellings for Rust-side resolution."""
    raw_names = sorted(
        {row.agent_clan for unit in units for row in unit if row.agent_clan}
    )
    presented_names = sorted(
        {
            presented
            for unit in units
            for row in unit
            if (presented := row.presented_clan_reference_name())
        }
    )
    return tuple(dict.fromkeys((*raw_names, *presented_names, clan_name)))


def _member_wires(
    units: list[list[Agent]],
) -> tuple[ClanWaveMemberWire, ...]:
    key_by_suffix = {
        unit[0].raw_suffix: clan_wave_identity_key(unit[0])
        for unit in units
        if unit and unit[0].raw_suffix
    }

    wires: list[ClanWaveMemberWire] = []
    for unit in units:
        if not unit:
            continue
        anchor = unit[0]
        identity = clan_wave_identity_key(anchor)
        wire_name = anchor.agent_name or anchor.presented_identity_name or identity
        aliases = {
            name
            for row in unit
            for name in (row.agent_name, row.presented_identity_name)
            if name
        }
        wait_for = {target for row in unit for target in row.waiting_for if target}
        wait_for_beads = {
            bead_id for row in unit for bead_id in row.waiting_for_beads if bead_id
        }
        wait_for_hoods = {
            hood for row in unit for hood in row.waiting_for_hoods if hood
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
                key=identity,
                name=wire_name,
                aliases=tuple(sorted(aliases)),
                launch_key=_launch_key(anchor),
                wait_for=tuple(sorted(wait_for)),
                wait_for_beads=tuple(sorted(wait_for_beads)),
                wait_for_hoods=tuple(sorted(wait_for_hoods)),
                phase_bead_id=phase_bead_id,
                retry_of=key_by_suffix.get(retry_root) if retry_root else None,
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
    unique key, name, and launch key to produce the same single wave.
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
        specs.append((clan_wave_identity_key(row), row.agent_name, _launch_key(row)))
    return tuple(specs)


@lru_cache(maxsize=16)
def _simple_request(
    clan_names: tuple[str, ...],
    specs: tuple[tuple[str, str, str], ...],
) -> ClanWaveRequestWire:
    """Reuse immutable requests for unchanged, dependency-free rosters."""
    return ClanWaveRequestWire(
        clan_names=clan_names,
        members=tuple(
            ClanWaveMemberWire(key=key, name=name, launch_key=launch_key)
            for key, name, launch_key in specs
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
        or wire.waves[0].seal
        or wire.waves[0].number is None
        or wire.layered
        or wire.numbered_wave_count != 1
        or wire.has_seal
        or wire.unresolved
        or wire.waves[0].ghost_names
        or any(member.predecessor_keys for member in wire.members)
        or any(member.ghost_predecessors for member in wire.members)
        or any(member.external_wait_count for member in wire.members)
    ):
        return None
    member_keys = {member.key for member in request.members}
    ordered_keys = wire.waves[0].member_keys
    if len(ordered_keys) != len(request.members) or set(ordered_keys) != member_keys:
        return None
    identities = tuple(ordered_keys)
    ranks = tuple((member.key, member.rank) for member in wire.members)
    if {key for key, _rank in ranks} != member_keys:
        return None
    return _SimpleWaveLayout(
        identities=identities,
        ranks=ranks,
        members=tuple(
            _ClanWaveMemberView(
                identity=member.key,
                relative_label=str(wire.waves[0].number),
                wave_index=wire.waves[0].index,
                predecessors=(),
                ghost_predecessors=(),
                external_wait_count=member.external_wait_count,
            )
            for member in wire.members
        ),
        wave_index=wire.waves[0].index,
        wave_number=wire.waves[0].number,
        layered=wire.layered,
        numbered_wave_count=wire.numbered_wave_count,
        has_seal=wire.has_seal,
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
            wave_index=layout.wave_index,
            label_kind="number",
            number=layout.wave_number,
            rank=rank,
            open=is_open,
        )
        for identity, rank in layout.ranks
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
    # Fold over each member's anchor row only, matching the clan container's
    # direct-member aggregate. Session turns and other descendants never
    # contribute, so a Done anchor with a failed earlier turn stays Done.
    rows = [
        unit[0] for identity in identities if (unit := rows_by_identity.get(identity))
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
    if all(bucket == "Done" for bucket in buckets):
        return _ClanWaveState.DONE, False
    if all(bucket == "Waiting" for bucket in buckets):
        return _ClanWaveState.NOT_STARTED, True
    # A Done/Waiting mix is still in flight; loaded Done members beside a
    # ghost are complete, which the all-Done branch above already covers.
    return _ClanWaveState.IN_FLIGHT, unfinished


def project_clan_wave_model(
    clan_name: str,
    units: list[list[Agent]],
    *,
    status_buckets: dict[int, str] | None = None,
) -> tuple[ClanWaveSummary, dict[str, ClanWaveSlot]]:
    """Project one clan's direct-member units into layout and state views."""
    clan_names = _clan_names(clan_name, units)
    simple_specs = _simple_member_specs(units)
    if simple_specs is not None:
        request = _simple_request(clan_names, simple_specs)
        simple_layout = _simple_wave_layout(request)
        # Keep the core memo exercised on each projection; after the first
        # request this is a constant-time facade hit, and the expensive static
        # adapter views remain cached separately from the live state fold.
        project_clan_waves(request)
        if simple_layout is not None:
            rows_by_identity = {
                identity: [unit[0]]
                for identity, unit in zip(
                    (spec[0] for spec in simple_specs), units, strict=True
                )
            }
            state, is_open = _wave_state(
                simple_layout.identities,
                rows_by_identity,
                (),
                status_buckets,
            )
            summary = ClanWaveSummary(
                layered=simple_layout.layered,
                numbered_wave_count=simple_layout.numbered_wave_count,
                has_seal=simple_layout.has_seal,
                waves=(
                    _ClanWaveView(
                        number=simple_layout.wave_number,
                        kind="seal" if simple_layout.has_seal else "number",
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

    member_wires = _member_wires(units)
    request = ClanWaveRequestWire(clan_names=clan_names, members=member_wires)
    wire = project_clan_waves(request)
    rows_by_identity = {clan_wave_identity_key(unit[0]): unit for unit in units if unit}
    placement_by_key = {placement.key: placement for placement in wire.members}

    def member_identities(keys: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(key for key in keys if key in rows_by_identity)

    def predecessor_identities(keys: tuple[str, ...]) -> tuple[str, ...]:
        predecessor_keys = {
            predecessor
            for key in keys
            if (placement := placement_by_key.get(key)) is not None
            for predecessor in placement.predecessor_keys
        }
        # placements are already in core display order
        return tuple(
            placement.key
            for placement in wire.members
            if placement.key in predecessor_keys
        )

    wave_views: list[_ClanWaveView] = []
    wave_open_by_key: dict[str, bool] = {}
    wave_index_by_key: dict[str, int | None] = {}
    label_kind_by_key: dict[str, ClanWaveLabelKind] = {}
    number_by_key: dict[str, int] = {}

    for wave in wire.waves:
        identities = member_identities(wave.member_keys)
        state, is_open = _wave_state(
            identities,
            rows_by_identity,
            wave.ghost_names,
            status_buckets,
        )
        predecessors = predecessor_identities(wave.member_keys)
        kind: ClanWaveLabelKind = "seal" if wave.seal else "number"
        wave_views.append(
            _ClanWaveView(
                number=wave.number,
                kind=kind,
                member_identities=identities,
                ghost_names=wave.ghost_names,
                state=state,
                predecessor_identities=predecessors,
            )
        )
        for key in wave.member_keys:
            wave_open_by_key[key] = is_open
            wave_index_by_key[key] = None if wave.seal else wave.index
            label_kind_by_key[key] = kind
            if wave.number is not None:
                number_by_key[key] = wave.number

    if wire.unresolved:
        unresolved_keys = wire.unresolved
        identities = member_identities(unresolved_keys)
        state, is_open = _wave_state(
            identities,
            rows_by_identity,
            (),
            status_buckets,
        )
        predecessors = predecessor_identities(unresolved_keys)
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
        for key in unresolved_keys:
            wave_open_by_key[key] = is_open
            wave_index_by_key[key] = None
            label_kind_by_key[key] = "unresolved"

    slots: dict[str, ClanWaveSlot] = {}
    member_views: list[_ClanWaveMemberView] = []
    for placement in wire.members:
        key = placement.key
        if key not in rows_by_identity:
            continue
        kind = label_kind_by_key.get(key, "unresolved")
        member_number = number_by_key.get(key) if kind == "number" else None
        label = (
            str(member_number)
            if member_number is not None
            else ("∎" if kind == "seal" else "?")
        )
        wave_index = wave_index_by_key.get(key)
        slots[key] = ClanWaveSlot(
            wave_index=wave_index,
            label_kind=kind,
            number=member_number,
            rank=placement.rank,
            open=wave_open_by_key.get(key, False),
        )
        member_views.append(
            _ClanWaveMemberView(
                identity=key,
                relative_label=label,
                wave_index=wave_index,
                predecessors=placement.predecessor_keys,
                ghost_predecessors=placement.ghost_predecessors,
                external_wait_count=placement.external_wait_count,
            )
        )

    unresolved_identities = member_identities(wire.unresolved)
    return (
        ClanWaveSummary(
            layered=wire.layered,
            numbered_wave_count=wire.numbered_wave_count,
            has_seal=wire.has_seal,
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
