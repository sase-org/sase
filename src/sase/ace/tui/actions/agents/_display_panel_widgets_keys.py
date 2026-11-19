"""Row-identity and paint-key helpers for AgentList panel widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.agent_groups import (
    GroupingMode,
    machine_grouping_signature,
    status_bucket_for,
    status_grouping_signature,
)


@dataclass(frozen=True)
class PaintedRowFacts:
    """Grouping facts captured when a panel row was last painted.

    Held :class:`~sase.ace.tui.models.agent.Agent` objects are shared and
    mutated in place, so a gate that re-reads them cannot tell what the
    widget actually painted. These snapshots are immutable and compared
    against the incoming roster instead.
    """

    identity: Any
    grouping: tuple[Any, ...]
    tribe: Any
    status_bucket: str
    clan_wave: tuple[int | None, int] | None


def painted_row_facts(agent: Any, grouping_mode: GroupingMode) -> PaintedRowFacts:
    """Return the immutable grouping snapshot for one *agent* under *grouping_mode*."""
    if grouping_mode is GroupingMode.BY_STATUS:
        grouping: tuple[Any, ...] = status_grouping_signature(agent)
    elif grouping_mode is GroupingMode.BY_MACHINE:
        grouping = machine_grouping_signature(agent)
    else:
        grouping = ()
    clan_wave: tuple[int | None, int] | None = None
    if getattr(agent, "tree_depth", 0) > 0:
        slot = getattr(agent, "clan_wave_slot", None)
        if slot is not None:
            clan_wave = (slot.wave_index, slot.rank)
    return PaintedRowFacts(
        identity=getattr(agent, "identity", None),
        grouping=grouping,
        tribe=getattr(agent, "tribe", None),
        status_bucket=status_bucket_for(agent),
        clan_wave=clan_wave,
    )


def panel_painted_row_facts(
    agents: list[Any],
    grouping_mode: GroupingMode,
) -> tuple[PaintedRowFacts, ...]:
    """Return painted-row snapshots for every agent in *agents*."""
    return tuple(painted_row_facts(agent, grouping_mode) for agent in agents)


def panel_row_signature(
    agents: list[Any],
    grouping_mode: GroupingMode,
) -> tuple[tuple[Any, ...], ...]:
    """Return visible-row identities plus grouping signatures for *agents*."""
    return tuple(
        (facts.identity, facts.grouping, facts.tribe)
        for facts in panel_painted_row_facts(agents, grouping_mode)
    )


def panel_agents_match(current: list[Any], target: list[Any]) -> bool:
    """Return whether *current* already holds *target*'s rows and row content."""
    if len(current) != len(target):
        return False
    return all(
        old is new or old == new for old, new in zip(current, target, strict=True)
    )


def _sorted_items(mapping: dict[Any, Any] | None) -> tuple[tuple[Any, Any], ...]:
    return tuple(sorted(mapping.items())) if mapping else ()


def panel_fold_inputs(
    panel_agents: list[Any],
    *,
    fold_counts: dict[str, tuple[int, int]],
    visible_parent_keys: set[str],
    fully_expanded_parent_keys: set[str],
) -> tuple[dict[str, tuple[int, int]], set[str], set[str]]:
    """Restrict global fold inputs to the fold keys one panel's rows own.

    A panel's rows only read their own fold key: ``compute_fold_annotation``
    looks up ``fold_counts`` by the row's own key and the expanded checks test
    that same key for membership. Entries owned by other panels therefore
    cannot change what this panel paints, but they used to change its paint
    key and repaint it. Scoping to owned keys keeps every sensitivity the
    panel needs and drops the rest.
    """
    from ...models._agent_tree import agent_fold_key

    own_keys = {
        fold_key
        for agent in panel_agents
        if (fold_key := agent_fold_key(agent)) is not None
    }
    return (
        {
            fold_key: counts
            for fold_key, counts in (fold_counts or {}).items()
            if fold_key in own_keys
        },
        set(visible_parent_keys or ()) & own_keys,
        set(fully_expanded_parent_keys or ()) & own_keys,
    )


def panel_paint_key(
    *,
    jump_hints: dict[int, str] | None,
    banner_jump_hints: dict[tuple[str, ...], str] | None,
    marked: set[Any],
    unread: set[Any],
    marked_fold_keys: Any,
    fold_counts: dict[str, tuple[int, int]],
    attempt_number: int | None,
    current_group_key: tuple[str, ...] | None,
    tribe_labels: list[str | None] | None,
    panel_tribe: str | None,
    visible_parent_keys: set[str],
    fully_expanded_parent_keys: set[str],
    fold_registry: Any,
) -> tuple[Any, ...]:
    """Snapshot every non-row input that changes how a panel's rows paint."""
    return (
        _sorted_items(jump_hints),
        _sorted_items(banner_jump_hints),
        frozenset(marked),
        frozenset(unread),
        tuple(marked_fold_keys),
        _sorted_items(fold_counts),
        attempt_number,
        current_group_key,
        None if tribe_labels is None else tuple(tribe_labels),
        panel_tribe,
        frozenset(visible_parent_keys),
        frozenset(fully_expanded_parent_keys),
        (id(fold_registry), getattr(fold_registry, "version", None)),
    )
