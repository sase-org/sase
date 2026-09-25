"""Background persistence transactions for optimistic TUI agent kills."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING, cast

from ._clan_cleanup import clan_members_for_container
from ._dismiss_cleanup import agent_identity_from_wire
from ._dismiss_persistence import add_dismissed_batch
from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind
from ._kill_termination import (
    AgentSurvivorsError,
    Survivor,
    live_dismissed_agents,
    survivor_agents,
    survivors_error,
    terminate_agents,
    withhold_agent_side_effects,
)

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire


def _killing_compat_module() -> ModuleType:
    from . import _killing

    return _killing


def single_kill_targets(
    agent: Agent,
    kind: KillKind,
    cleanup_plan: AgentCleanupPlanWire | None,
    agents_with_children: list[Agent],
) -> list[tuple[Agent, KillKind]]:
    """Return every row one focused kill signals, with each row's kill kind.

    The focused row comes first, then the plan's other kill items, or the
    live members of a clan container when there is no plan. The optimistic
    TUI stage and the durable persist-cleanup stage both resolve targets
    here so they always agree on which processes a kill covers.
    """
    by_identity = {candidate.identity: candidate for candidate in agents_with_children}
    kinds: dict[AgentIdentity, KillKind] = {}
    targets = [agent]
    if cleanup_plan is not None:
        for item in cleanup_plan.kill_items:
            identity = agent_identity_from_wire(item.identity)
            kinds[identity] = cast(KillKind, item.kind)
            candidate = by_identity.get(identity)
            if candidate is not None:
                targets.append(candidate)
    else:
        targets.extend(clan_members_for_container(agent, agents_with_children))
    seen: set[AgentIdentity] = set()
    resolved: list[tuple[Agent, KillKind]] = []
    for target in targets:
        if target.identity in seen:
            continue
        seen.add(target.identity)
        resolved.append((target, kinds.get(target.identity, kind)))
    return resolved


def persist_single_kill_transaction(
    agent: Agent,
    kind: KillKind,
    agents_with_children_snapshot: list[Agent],
    added: set[AgentIdentity],
    cleanup_plan: AgentCleanupPlanWire | None,
    related_agents: list[Agent],
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Persist all side effects for one optimistic kill operation.

    Order matters. The dismissal and notification side effects go first so
    other TUIs and restarts see the removal at once. The agent's whole process
    set is then terminated and verified dead. Only after that are workspace
    claims released and artifacts deleted, and never for an agent that could
    not be verified dead; those are reported as an error once everything else
    is persisted.

    *added* is this operation's identities. They merge into the on-disk
    dismissed index, so concurrent cleanup procs never overwrite each other.
    """
    killing_compat = _killing_compat_module()
    dismissed = add_dismissed_batch(added)
    if dismissed is not None:
        killing_compat.sync_dismissed_agent_artifact_index(dismissed)
    killing_compat.dismiss_notifications_for_agents(related_agents)

    targets = single_kill_targets(
        agent, kind, cleanup_plan, agents_with_children_snapshot
    )
    kill_agents = [
        target for target, target_kind in targets if target_kind != "monitor"
    ]
    survivors: list[Survivor] = terminate_agents(
        [
            *kill_agents,
            *live_dismissed_agents(
                related_agents,
                handled_pids={target.pid for target in kill_agents if target.pid},
            ),
        ]
    )
    survivor_rows = survivor_agents(survivors)
    survivor_identities = {row.identity for row in survivor_rows}
    if agent.identity not in survivor_identities:
        effects_plan = withhold_agent_side_effects(
            cleanup_plan, survivor_rows, agents_with_children_snapshot
        )
        args: list[object] = [agent, kind, agents_with_children_snapshot]
        if effects_plan is not None:
            args.append(effects_plan)
        if register_expected_deletion is None:
            killing_compat.persist_kill_side_effects(*args)
        else:
            killing_compat.persist_kill_side_effects(
                *args, register_expected_deletion=register_expected_deletion
            )
    if survivors:
        error: AgentSurvivorsError = survivors_error(survivors)
        raise error


def persist_bulk_kill_transaction(
    kill_items: list[BulkKillItem],
    dismissable: list[Agent],
    added: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    cleanup_plan: object | None,
    recent_group: SavedAgentGroupWire | None,
    proc_stops: list[Agent] | None = None,
    gate_cancels: list[Agent] | None = None,
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Persist all side effects for one optimistic bulk kill/dismiss operation.

    Follows the same order as :func:`persist_single_kill_transaction`:
    publish the dismissal, stop member proc shells, cancel member gates,
    terminate and verify, then release workspaces and delete artifacts for
    every agent that is verifiably dead. A member stop or cancel that does
    not settle fails the transaction with the identities to resurface.
    *added* is this operation's identities, merged into the dismissed index.
    """
    killing_compat = _killing_compat_module()
    dismissed = add_dismissed_batch(added)
    if dismissed is not None:
        try:
            killing_compat.sync_dismissed_agent_artifact_index(dismissed)
        except Exception:
            pass
    dismissed_rows = [item.agent for item in kill_items] + list(dismissable)
    if dismissed_rows:
        killing_compat.dismiss_notifications_for_agents(dismissed_rows)

    _execute_member_stop_intents(proc_stops, gate_cancels)

    kill_agents = [item.agent for item in kill_items if item.kind != "monitor"]
    survivors: list[Survivor] = terminate_agents(
        [
            *kill_agents,
            *live_dismissed_agents(
                dismissable,
                handled_pids={agent.pid for agent in kill_agents if agent.pid},
            ),
        ]
    )
    survivor_rows = survivor_agents(survivors)
    if survivor_rows:
        survivor_identities = {row.identity for row in survivor_rows}
        kill_items = [
            item
            for item in kill_items
            if item.agent.identity not in survivor_identities
        ]
        dismissable = [
            row for row in dismissable if row.identity not in survivor_identities
        ]
        cleanup_plan = withhold_agent_side_effects(
            cleanup_plan, survivor_rows, agents_with_children_snapshot
        )

    args: list[object] = [
        kill_items,
        dismissable,
        added,
        agents_with_children_snapshot,
    ]
    if cleanup_plan is not None or recent_group is not None:
        args.extend([cleanup_plan, recent_group])
    kwargs: dict[str, object] = {"publish_dismissal": False}
    if register_expected_deletion is not None:
        kwargs["register_expected_deletion"] = register_expected_deletion
    killing_compat.persist_bulk_kill_side_effects(*args, **kwargs)
    if survivors:
        error: AgentSurvivorsError = survivors_error(survivors)
        raise error


def _execute_member_stop_intents(
    proc_stops: list[Agent] | None,
    gate_cancels: list[Agent] | None,
) -> None:
    """Stop member proc shells and cancel member gates, failing on leftovers.

    Raises :class:`MemberStopError` naming the identities whose rows must
    resurface when any stop or cancel does not settle.
    """
    from ._kill_member_intents import (
        MemberStopError,
        execute_gate_cancel_intents,
        execute_proc_stop_intents,
    )

    failed: set[AgentIdentity] = set()
    failed.update(execute_proc_stop_intents(list(proc_stops or ())))
    failed.update(execute_gate_cancel_intents(list(gate_cancels or ())))
    if failed:
        names = ", ".join(sorted(str(identity) for identity in failed))
        raise MemberStopError(
            f"Could not stop {names}; those rows remain visible",
            resurface_identities=set(failed),
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
