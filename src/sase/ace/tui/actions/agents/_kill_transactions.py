"""Background persistence transactions for optimistic TUI agent kills."""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire


def _killing_compat_module() -> ModuleType:
    from . import _killing

    return _killing


def persist_single_kill_transaction(
    agent: Agent,
    kind: KillKind,
    agents_with_children_snapshot: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    cleanup_plan: AgentCleanupPlanWire | None,
    related_agents: list[Agent],
) -> None:
    """Persist all side effects for one optimistic kill operation."""
    from ....dismissed_agents import save_dismissed_agents

    killing_compat = _killing_compat_module()
    if cleanup_plan is None:
        consumed_intents_result = killing_compat.persist_kill_side_effects(
            agent,
            kind,
            agents_with_children_snapshot,
        )
    else:
        consumed_intents_result = killing_compat.persist_kill_side_effects(
            agent,
            kind,
            agents_with_children_snapshot,
            cleanup_plan,
        )
    consumed_intents = consumed_intents_result is True
    # Persist the dismissed-set snapshot captured on the UI thread, then
    # rewrite the notifications file (single read+write) for this agent and
    # any workflow-child rows hidden alongside it.
    save_dismissed_agents(dismissed_snapshot)
    killing_compat.sync_dismissed_agent_artifact_index(dismissed_snapshot)
    if not consumed_intents:
        killing_compat.dismiss_notifications_for_agents(related_agents)


def persist_bulk_kill_transaction(
    kill_items: list[BulkKillItem],
    dismissable: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    cleanup_plan: object | None,
    recent_group: SavedAgentGroupWire | None,
) -> None:
    """Persist all side effects for one optimistic bulk kill/dismiss operation."""
    killing_compat = _killing_compat_module()
    if cleanup_plan is None:
        if recent_group is None:
            killing_compat.persist_bulk_kill_side_effects(
                kill_items,
                dismissable,
                dismissed_snapshot,
                agents_with_children_snapshot,
            )
        else:
            killing_compat.persist_bulk_kill_side_effects(
                kill_items,
                dismissable,
                dismissed_snapshot,
                agents_with_children_snapshot,
                None,
                recent_group,
            )
        return
    killing_compat.persist_bulk_kill_side_effects(
        kill_items,
        dismissable,
        dismissed_snapshot,
        agents_with_children_snapshot,
        cleanup_plan,
        recent_group,
    )


def bulk_kill_task_display_name(killed_count: int, dismissed_count: int) -> str:
    """Return the Task Queue label for a bulk kill/dismiss persistence task."""
    if killed_count and dismissed_count:
        return f"kill {killed_count} + dismiss {dismissed_count} agents"
    if killed_count:
        return f"kill {killed_count} agent{'s' if killed_count != 1 else ''}"
    return f"dismiss {dismissed_count} agent{'s' if dismissed_count != 1 else ''}"


def bulk_kill_summary(killed_count: int, dismissed_count: int) -> str:
    """Return the completion message for a bulk kill/dismiss persistence task."""
    kill_msg = (
        f"Killed {killed_count} agent{'s' if killed_count != 1 else ''}"
        if killed_count
        else ""
    )
    dismiss_msg = (
        f"dismissed {dismissed_count} agent{'s' if dismissed_count != 1 else ''}"
        if dismissed_count
        else ""
    )
    if killed_count and dismissed_count:
        return f"{kill_msg} and {dismiss_msg}"
    if killed_count:
        return kill_msg
    return dismiss_msg.capitalize()
