"""Visible-row layout for layered clan wave gutters."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from ..models._agent_clan_waves import ClanWaveSlot
from ..models.agent import Agent

ClanKey = tuple[str, str | None]
WaveKey = tuple[str, str | None, str, int | None]


@dataclass(frozen=True)
class ClanWaveGutter:
    """Five-cell prefix contribution for one visible clan row."""

    label: str | None = None
    label_kind: str | None = None
    bracket: str | None = None
    lane: bool | None = None
    open: bool | None = None


def _clan_key(agent: Agent) -> ClanKey | None:
    name = agent.presented_clan_reference_name() or agent.agent_clan
    if not name:
        return None
    return name, agent.agent_clan_generation


def layered_clan_keys(agents: Iterable[Agent]) -> frozenset[ClanKey]:
    """Return the clan generations whose list order follows wave rank."""
    return frozenset(
        key
        for agent in agents
        if agent.is_clan_container
        and agent.clan_waves is not None
        and agent.clan_waves.layered
        and (key := _clan_key(agent)) is not None
    )


def _wave_key(agent: Agent, slot: ClanWaveSlot) -> WaveKey | None:
    clan = _clan_key(agent)
    if clan is None:
        return None
    return (*clan, slot.label_kind, slot.wave_index)


def _direct_anchor(
    agent: Agent,
    rows_by_suffix: dict[str, Agent],
) -> Agent | None:
    """Resolve a visible descendant to the direct clan member that owns it."""
    current = agent
    visited: set[str] = set()
    while current.tree_depth > 0:
        if current.tree_depth == 1:
            return current if current.clan_wave_slot is not None else None
        parent_key = current.tree_parent_key
        if not parent_key or parent_key in visited:
            return None
        visited.add(parent_key)
        parent = rows_by_suffix.get(parent_key)
        if parent is None:
            return None
        current = parent
    return None


def _display_label(slot: ClanWaveSlot) -> str:
    if slot.label_kind == "seal":
        return "∎"
    if slot.label_kind == "unresolved":
        return "?"
    if slot.number is None:
        return "?"
    return str(slot.number) if slot.number <= 99 else "…"


def build_clan_wave_gutters(
    agents: list[Agent],
    visible_order: Iterable[int],
) -> dict[int, ClanWaveGutter]:
    """Build wave prefixes from the visible rows, so folds and queries shape braces.

    ``visible_order`` contains local agent indices in rendered tree order. The
    projection itself owns wave membership and rank; this pass only decides
    which visible anchors carry labels/brackets and which descendants keep a
    continuation lane open.
    """
    layered_clans = layered_clan_keys(agents)
    if not layered_clans:
        return {}

    rows_by_suffix = {agent.raw_suffix: agent for agent in agents if agent.raw_suffix}
    ordered_indices = [index for index in visible_order if 0 <= index < len(agents)]
    visible_anchors: list[tuple[int, Agent, ClanWaveSlot, WaveKey]] = []
    for index in ordered_indices:
        agent = agents[index]
        slot = agent.clan_wave_slot
        key = _clan_key(agent)
        wave_key = _wave_key(agent, slot) if slot is not None else None
        if (
            agent.tree_depth == 1
            and slot is not None
            and key in layered_clans
            and wave_key is not None
        ):
            visible_anchors.append((index, agent, slot, wave_key))

    gutters: dict[int, ClanWaveGutter] = {}
    visible_ranks_by_wave: dict[WaveKey, set[int]] = {}
    for _, _, slot, wave_key in visible_anchors:
        visible_ranks_by_wave.setdefault(wave_key, set()).add(slot.rank)

    start = 0
    while start < len(visible_anchors):
        end = start + 1
        wave_key = visible_anchors[start][3]
        while end < len(visible_anchors) and visible_anchors[end][3] == wave_key:
            end += 1
        run = visible_anchors[start:end]
        count = len(run)
        for offset, (index, _agent, slot, _key) in enumerate(run):
            if count == 1:
                bracket = "─"
            elif offset == 0:
                bracket = "╭"
            elif offset == count - 1:
                bracket = "╰"
            else:
                bracket = "├"
            gutters[index] = ClanWaveGutter(
                label=_display_label(slot) if offset == 0 else None,
                label_kind=slot.label_kind if offset == 0 else None,
                bracket=bracket,
                open=slot.open if offset == 0 else None,
            )
        start = end

    for index in ordered_indices:
        if index in gutters:
            continue
        agent = agents[index]
        anchor = _direct_anchor(agent, rows_by_suffix)
        if anchor is None:
            continue
        key = _clan_key(anchor)
        slot = anchor.clan_wave_slot
        wave_key = _wave_key(anchor, slot) if slot is not None else None
        if key not in layered_clans or slot is None or wave_key is None:
            continue
        later_member_visible = any(
            rank > slot.rank for rank in visible_ranks_by_wave.get(wave_key, set())
        )
        gutters[index] = ClanWaveGutter(lane=later_member_visible)
    return gutters


__all__ = ["ClanWaveGutter", "build_clan_wave_gutters", "layered_clan_keys"]
