"""Rust-backed deterministic clan attribute resolution facade."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ClanTribeMemberWire:
    """One launched member considered for clan attribute declarations."""

    agent_clan: str
    launch_timestamp: str
    identity: str
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    clan_summary: str | None = None


@dataclass(frozen=True)
class _ClanTribeResolutionWire:
    """Resolved tribe and the member declaration that supplied it."""

    clan_name: str
    generation: str | None = None
    tribe: str | None = None
    source_launch_timestamp: str | None = None
    source_identity: str | None = None


@dataclass(frozen=True)
class _ClanSummaryResolutionWire:
    """Resolved summary and the member declaration that supplied it."""

    clan_name: str
    generation: str | None = None
    summary: str | None = None
    source_launch_timestamp: str | None = None
    source_identity: str | None = None


def resolve_clan_tribe(
    clan_name: str,
    generation: str | None,
    members: list[ClanTribeMemberWire],
) -> _ClanTribeResolutionWire:
    """Resolve the latest explicit declaration for one clan generation."""
    resolve = require_rust_binding("resolve_clan_tribe")
    payload = resolve(
        {
            "clan_name": clan_name,
            "generation": generation,
            "members": [asdict(member) for member in members],
        }
    )
    return _ClanTribeResolutionWire(
        clan_name=str(payload["clan_name"]),
        generation=payload.get("generation"),
        tribe=payload.get("tribe"),
        source_launch_timestamp=payload.get("source_launch_timestamp"),
        source_identity=payload.get("source_identity"),
    )


def resolve_clan_summary(
    clan_name: str,
    generation: str | None,
    members: list[ClanTribeMemberWire],
) -> _ClanSummaryResolutionWire:
    """Resolve the latest explicit summary for one clan generation."""
    resolve = require_rust_binding("resolve_clan_summary")
    payload = resolve(
        {
            "clan_name": clan_name,
            "generation": generation,
            "members": [asdict(member) for member in members],
        }
    )
    return _ClanSummaryResolutionWire(
        clan_name=str(payload["clan_name"]),
        generation=payload.get("generation"),
        summary=payload.get("summary"),
        source_launch_timestamp=payload.get("source_launch_timestamp"),
        source_identity=payload.get("source_identity"),
    )


__all__ = [
    "ClanTribeMemberWire",
    "resolve_clan_summary",
    "resolve_clan_tribe",
]
