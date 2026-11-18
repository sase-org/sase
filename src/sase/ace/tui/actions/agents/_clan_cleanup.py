"""Shared clan-membership helpers for kill and dismissal cascades."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


def clan_members_for_container(
    container: Agent,
    agents_with_children: list[Agent],
) -> list[Agent]:
    """Return live members for a synthetic clan container's generation.

    Killing an ordinary member must leave its siblings alone, so only a
    rootless synthetic row (no artifact suffix) activates the new cascade.
    The legacy branch preserves archived parallel-session root behavior.
    """
    if container.is_clan_container and container.agent_clan:
        from ...models._agent_tree import agent_fold_key

        container_key = agent_fold_key(container)
        return [
            candidate
            for candidate in agents_with_children
            if candidate.identity != container.identity
            and (
                candidate.tree_parent_key == container_key
                or candidate.agent_clan == container.agent_clan
            )
            and (
                container.agent_clan_generation is None
                or candidate.agent_clan_generation is None
                or candidate.agent_clan_generation == container.agent_clan_generation
            )
            and not candidate.is_clan_container
        ]
    if (
        container.is_workflow_child
        or not container.agent_session_parallel
        or container.raw_suffix is None
    ):
        return []
    return [
        candidate
        for candidate in agents_with_children
        if candidate.identity != container.identity
        and candidate.agent_session_parallel
        and candidate.parent_workflow is None
        and candidate.parent_timestamp == container.raw_suffix
    ]


def expand_clan_containers_for_cleanup(
    agents: list[Agent],
    agents_with_children: list[Agent],
) -> list[Agent]:
    """Replace synthetic clan containers with their live members.

    Folded clan members live in ``agents_with_children`` but not in the
    visible Agents-tab list. Bulk dismiss/kill and cleanup-panel counts need
    those members without selecting the suffix-less container itself.
    """
    expanded: list[Agent] = []
    seen: set[tuple[object, str, str | None]] = set()

    def add(agent: Agent) -> None:
        if agent.identity in seen:
            return
        seen.add(agent.identity)
        expanded.append(agent)

    for agent in agents:
        if agent.is_clan_container:
            for member in clan_members_for_container(agent, agents_with_children):
                add(member)
            continue
        add(agent)
    return expanded


def cancel_pending_batches_for_clan_selection(agents: list[Agent]) -> int:
    """Persist explicit clan-generation cancellation for selected containers.

    Must be called with the explicit container selection before
    :func:`expand_clan_containers_for_cleanup` loses the container
    identity. Individual member rows never trigger cancellation; only a
    synthetic clan container does. Returns the number of batches cancelled.
    """
    try:
        from sase.axe.chop_batch_recovery import cancel_chop_batches_for_clan
    except Exception as exc:
        raise RuntimeError(f"unable to load chop batch cancellation: {exc}") from exc
    cancelled = 0
    failures: list[str] = []
    for agent in agents:
        try:
            is_container = bool(getattr(agent, "is_clan_container", False))
        except Exception:
            continue
        if not is_container:
            continue
        clan = str(getattr(agent, "agent_clan", "") or "")
        if not clan:
            continue
        generation = getattr(agent, "agent_clan_generation", None)
        try:
            cancelled += len(
                cancel_chop_batches_for_clan(
                    clan,
                    generation=str(generation) if generation is not None else None,
                    reason=f"explicit TUI clan kill of {clan}",
                )
            )
        except Exception as exc:
            failures.append(f"{clan}: {exc}")
    if failures:
        raise RuntimeError(
            "unable to persist chop batch cancellation before clan cleanup: "
            + "; ".join(failures)
        )
    return cancelled


__all__ = [
    "cancel_pending_batches_for_clan_selection",
    "clan_members_for_container",
    "expand_clan_containers_for_cleanup",
]
