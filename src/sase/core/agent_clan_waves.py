"""Rust-backed clan dependency-wave projection facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ClanWaveMemberWire:
    """One loaded direct clan member and its declared waits."""

    key: str
    name: str
    aliases: tuple[str, ...] = ()
    launch_key: str = ""
    wait_for: tuple[str, ...] = ()
    wait_for_beads: tuple[str, ...] = ()
    wait_for_hoods: tuple[str, ...] = ()
    phase_bead_id: str | None = None
    retry_of: str | None = None
    seal: bool = False


@dataclass(frozen=True)
class ClanWaveRequestWire:
    """Inputs for projecting one clan generation."""

    clan_names: tuple[str, ...] = ()
    members: tuple[ClanWaveMemberWire, ...] = ()
    _cached_hash: int = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cached_hash", hash((self.clan_names, self.members)))

    def __hash__(self) -> int:
        """Keep repeated warm-cache lookups constant-time for large clans."""
        return self._cached_hash


@dataclass(frozen=True)
class _ClanWaveWire:
    """One numbered layer or the optional seal layer."""

    index: int
    number: int | None
    seal: bool
    member_keys: tuple[str, ...] = ()
    ghost_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ClanWaveMemberPlacementWire:
    """Final display placement and dependency detail for one member."""

    key: str
    wave_index: int | None
    rank: int
    predecessor_keys: tuple[str, ...] = ()
    ghost_predecessors: tuple[str, ...] = ()
    external_wait_count: int = 0


@dataclass(frozen=True)
class ClanWavesWire:
    """Resolved layout and all loaded member placements."""

    layered: bool = False
    numbered_wave_count: int = 0
    has_seal: bool = False
    waves: tuple[_ClanWaveWire, ...] = ()
    members: tuple[_ClanWaveMemberPlacementWire, ...] = ()
    unresolved: tuple[str, ...] = ()


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _int_or_none(value: Any) -> int | None:
    if type(value) is int:
        return value
    return None


def _project_clan_waves_uncached(request: ClanWaveRequestWire) -> ClanWavesWire:
    binding = require_rust_binding("project_clan_waves")
    payload = binding(
        {
            "clan_names": list(request.clan_names),
            "members": [
                {
                    "key": member.key,
                    "name": member.name,
                    "aliases": list(member.aliases),
                    "launch_key": member.launch_key,
                    "wait_for": list(member.wait_for),
                    "wait_for_beads": list(member.wait_for_beads),
                    "wait_for_hoods": list(member.wait_for_hoods),
                    "phase_bead_id": member.phase_bead_id,
                    "retry_of": member.retry_of,
                    "seal": member.seal,
                }
                for member in request.members
            ],
        }
    )
    if not isinstance(payload, dict):
        return ClanWavesWire()

    waves_value = payload.get("waves", ())
    if not isinstance(waves_value, (list, tuple)):
        waves_value = ()
    waves = tuple(
        _ClanWaveWire(
            index=_int_or_none(item.get("index")) or 0,
            number=_int_or_none(item.get("number")),
            seal=item.get("seal") is True,
            member_keys=_tuple_of_strings(item.get("member_keys")),
            ghost_names=_tuple_of_strings(item.get("ghost_names")),
        )
        for item in waves_value
        if isinstance(item, dict)
    )

    members_value = payload.get("members", ())
    if not isinstance(members_value, (list, tuple)):
        members_value = ()
    members = tuple(
        _ClanWaveMemberPlacementWire(
            key=item["key"],
            wave_index=_int_or_none(item.get("wave_index")),
            rank=_int_or_none(item.get("rank")) or 0,
            predecessor_keys=_tuple_of_strings(item.get("predecessor_keys")),
            ghost_predecessors=_tuple_of_strings(item.get("ghost_predecessors")),
            external_wait_count=_int_or_none(item.get("external_wait_count")) or 0,
        )
        for item in members_value
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    )
    numbered_wave_count = _int_or_none(payload.get("numbered_wave_count"))
    if numbered_wave_count is None:
        numbered_wave_count = sum(wave.number is not None for wave in waves)
    return ClanWavesWire(
        layered=payload.get("layered") is True,
        numbered_wave_count=numbered_wave_count,
        has_seal=(
            payload.get("has_seal") is True
            if isinstance(payload.get("has_seal"), bool)
            else any(wave.seal for wave in waves)
        ),
        waves=waves,
        members=members,
        unresolved=_tuple_of_strings(payload.get("unresolved")),
    )


@lru_cache(maxsize=128)
def project_clan_waves(request: ClanWaveRequestWire) -> ClanWavesWire:
    """Project a clan's declared waits through the bounded Rust-backed cache."""
    return _project_clan_waves_uncached(request)


__all__ = [
    "ClanWaveMemberWire",
    "ClanWaveRequestWire",
    "ClanWavesWire",
    "project_clan_waves",
]
