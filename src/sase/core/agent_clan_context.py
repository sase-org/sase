"""Shared generation-scoped clan context projections."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sase.core.agent_scan_wire import AgentClanContextWire

ClanContextKey = tuple[str, str | None]


def _clean(value: str | None) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    return cleaned or None


def clan_context_key(
    agent_clan: str | None,
    agent_clan_generation: str | None,
) -> ClanContextKey | None:
    """Return the exact normalized key for one clan generation."""
    clan = _clean(agent_clan)
    if clan is None:
        return None
    return (clan, _clean(agent_clan_generation))


def clan_context_by_key(
    contexts: Iterable[AgentClanContextWire],
) -> dict[ClanContextKey, AgentClanContextWire]:
    """Index snapshot context by exact clan name and generation."""
    result: dict[ClanContextKey, AgentClanContextWire] = {}
    for context in contexts:
        key = clan_context_key(
            context.agent_clan,
            context.agent_clan_generation,
        )
        if key is not None:
            result[key] = context
    return result


def clan_context_for(
    contexts: Mapping[ClanContextKey, AgentClanContextWire],
    *,
    agent_clan: str | None,
    agent_clan_generation: str | None,
) -> AgentClanContextWire | None:
    """Look up semantic context without falling across generations."""
    key = clan_context_key(agent_clan, agent_clan_generation)
    return contexts.get(key) if key is not None else None


def effective_clan_attributes(
    *,
    declared_tribe: str | None,
    declared_summary: str | None,
    context: AgentClanContextWire | None,
) -> tuple[str | None, str | None]:
    """Resolve context-backed clan attributes over visible declarations."""
    context_tribe = _clean(context.clan_tribe) if context is not None else None
    context_summary = _clean(context.clan_summary) if context is not None else None
    return (
        context_tribe or _clean(declared_tribe),
        context_summary or _clean(declared_summary),
    )


def effective_agent_tribe(
    *,
    standalone_tribe: str | None,
    declared_clan_tribe: str | None,
    context: AgentClanContextWire | None,
) -> str | None:
    """Project a list-facing tribe while preserving standalone assignments."""
    clan_tribe, _ = effective_clan_attributes(
        declared_tribe=declared_clan_tribe,
        declared_summary=None,
        context=context,
    )
    return clan_tribe or _clean(standalone_tribe)


__all__ = [
    "ClanContextKey",
    "clan_context_by_key",
    "clan_context_for",
    "clan_context_key",
    "effective_agent_tribe",
    "effective_clan_attributes",
]
