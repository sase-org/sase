"""Rust-backed clan dependency-wave projection facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ClanWaveMemberWire:
    """One loaded direct clan member and its declared waits."""

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

    clan_name: str
    members: tuple[ClanWaveMemberWire, ...] = ()
    _cached_hash: int = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cached_hash", hash((self.clan_name, self.members)))

    def __hash__(self) -> int:
        """Keep repeated warm-cache lookups constant-time for large clans."""
        return self._cached_hash


@dataclass(frozen=True)
class ClanWavesWire:
    """Resolved layers, member placements, and edge metadata."""

    waves: tuple[tuple[str, ...], ...] = ()
    wave_of: tuple[tuple[str, int], ...] = ()
    preds: tuple[tuple[str, tuple[str, ...]], ...] = ()
    external_waits: tuple[tuple[str, int], ...] = ()
    ghosts: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    seal: tuple[str, ...] = ()


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _project_clan_waves_uncached(request: ClanWaveRequestWire) -> ClanWavesWire:
    binding = require_rust_binding("project_clan_waves")
    payload = binding(
        {
            "clan_name": request.clan_name,
            "members": [
                {
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

    waves_value = payload.get("waves", ())
    waves = tuple(
        _tuple_of_strings(wave)
        for wave in waves_value
        if isinstance(wave, (list, tuple))
    )
    wave_of_value = payload.get("wave_of", {})
    wave_of = tuple(
        sorted(
            (name, int(number))
            for name, number in wave_of_value.items()
            if isinstance(name, str) and isinstance(number, int)
        )
    )
    preds_value = payload.get("preds", {})
    preds = tuple(
        sorted(
            (name, _tuple_of_strings(predecessors))
            for name, predecessors in preds_value.items()
            if isinstance(name, str)
        )
    )
    external_value = payload.get("external_waits", {})
    external_waits = tuple(
        sorted(
            (name, int(count))
            for name, count in external_value.items()
            if isinstance(name, str) and isinstance(count, int)
        )
    )
    return ClanWavesWire(
        waves=waves,
        wave_of=wave_of,
        preds=preds,
        external_waits=external_waits,
        ghosts=_tuple_of_strings(payload.get("ghosts")),
        unresolved=_tuple_of_strings(payload.get("unresolved")),
        seal=_tuple_of_strings(payload.get("seal")),
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
