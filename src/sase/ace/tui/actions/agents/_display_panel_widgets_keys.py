"""Row-identity and paint-key helpers for AgentList panel widgets."""

from __future__ import annotations

from typing import Any

from ...models.agent_groups import (
    GroupingMode,
    machine_grouping_signature,
    status_grouping_signature,
)


def panel_row_signature(
    agents: list[Any],
    grouping_mode: GroupingMode,
) -> tuple[tuple[Any, ...], ...]:
    """Return visible-row identities plus grouping signatures for *agents*."""
    rows: list[tuple[Any, ...]] = []
    for agent in agents:
        identity = getattr(agent, "identity", None)
        if grouping_mode is GroupingMode.BY_STATUS:
            extra: tuple[Any, ...] = status_grouping_signature(agent)
        elif grouping_mode is GroupingMode.BY_MACHINE:
            extra = machine_grouping_signature(agent)
        else:
            extra = ()
        rows.append((identity, extra, getattr(agent, "tribe", None)))
    return tuple(rows)


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
