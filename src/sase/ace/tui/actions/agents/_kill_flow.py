"""Optimistic UI flow for single and bulk TUI agent kills."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from ._dismiss_cleanup import agent_identity_from_wire, dismissed_identities_from_plan
from ._clan_cleanup import clan_members_for_container
from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind
from ._recent_dismissal_groups import (
    agents_for_recent_group,
    build_recent_dismissed_agent_group,
    cache_recent_dismissed_agent_group,
)

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire

log = logging.getLogger(__name__)


class AgentKillFlowMixin:
    """Mixin for immediate, optimistic kill and kill/dismiss workflows."""

    _agents_with_children: list[Agent]
    _dismissed_agents: set[AgentIdentity]

    def _do_kill_agent(
        self,
        agent: Agent,
        cleanup_plan: AgentCleanupPlanWire | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        """Perform the actual agent kill after confirmation.

        *on_settled*, when given, runs once the kill's durable persistence
        proc has settled (or immediately, if submission itself is rejected)
        so a caller composing a kill-and-edit relaunch can defer an action
        until it is safe to do so. Returns whether a kill was actually
        initiated (and therefore whether *on_settled* will fire).
        """
        started = time.perf_counter()
        kind: KillKind | None = self._classify_kill_kind(agent)  # type: ignore[attr-defined]
        if cleanup_plan is not None:
            matching = next(
                (
                    item
                    for item in cleanup_plan.kill_items
                    if agent_identity_from_wire(item.identity) == agent.identity
                ),
                None,
            )
            if matching is not None:
                kind = cast(KillKind, matching.kind)
            elif cleanup_plan.kill_items and kind is None:
                kind = cast(KillKind, cleanup_plan.kill_items[0].kind)
        if kind is None:
            self.notify(  # type: ignore[attr-defined]
                f"Unknown agent type: {agent.agent_type}", severity="error"
            )
            if on_settled is not None:
                on_settled()
            return False

        agents_with_children_snapshot = list(self._agents_with_children)
        by_identity = {
            candidate.identity: candidate for candidate in agents_with_children_snapshot
        }
        kill_targets = [agent]
        if cleanup_plan is not None:
            kill_targets.extend(
                candidate
                for item in cleanup_plan.kill_items
                if (
                    candidate := by_identity.get(
                        agent_identity_from_wire(item.identity)
                    )
                )
                is not None
                and candidate.identity != agent.identity
            )
        else:
            kill_targets.extend(
                clan_members_for_container(
                    agent,
                    agents_with_children_snapshot,
                )
            )

        kill_kinds = {
            agent_identity_from_wire(item.identity): item.kind
            for item in (cleanup_plan.kill_items if cleanup_plan is not None else ())
        }
        signaled: set[AgentIdentity] = set()
        signal_failed = False
        for target in kill_targets:
            if target.identity in signaled:
                continue
            signaled.add(target.identity)
            target_kind = kill_kinds.get(target.identity, kind)
            if target_kind == "monitor":
                continue
            if target.pid is not None and not self._kill_agent_process_group(target):  # type: ignore[attr-defined]
                signal_failed = True
        if signal_failed:
            if on_settled is not None:
                on_settled()
            return False
        self._notify_killed_agent(agent, kind)  # type: ignore[attr-defined]

        immediate_identities = self._collect_planned_kill_identities(  # type: ignore[attr-defined]
            agent,
            cleanup_plan,
        )
        from ....dismissed_agents import snapshot_dismissed_agents

        # Snapshot the dismissed set BEFORE the optimistic mutation so re-entrant
        # kills cannot corrupt the set the persistence worker writes back.
        dismissed_snapshot = snapshot_dismissed_agents(self._dismissed_agents)
        dismissed_snapshot.update(immediate_identities)
        self._apply_killed_agents_in_memory(immediate_identities)  # type: ignore[attr-defined]

        self._submit_kill_persistence_proc(  # type: ignore[attr-defined]
            agent,
            kind,
            agents_with_children_snapshot,
            dismissed_snapshot,
            cleanup_plan,
            on_settled=on_settled,
        )
        log.debug(
            "agent kill immediate stage: kind=%s identity=%s elapsed=%.3fs",
            kind,
            agent.identity,
            time.perf_counter() - started,
        )
        return True

    def _do_bulk_kill_agents(
        self,
        killable: list[Agent],
        dismissable: list[Agent] | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        """Kill/dismiss marked agents as one optimistic UI transaction.

        *on_settled*, when given, runs once the bulk kill/dismiss's durable
        persistence proc has settled (or immediately, if nothing was
        submitted or submission itself is rejected) so a caller composing a
        marked kill-and-edit relaunch can defer an action until it is safe
        to do so. Returns whether any kill/dismiss was actually initiated
        (and therefore whether *on_settled* will fire).
        """
        from . import _killing as killing_compat

        started = time.perf_counter()
        dismissable = dismissable or []
        agents_with_children_snapshot = list(self._agents_with_children)
        live_ids = {a.identity for a in agents_with_children_snapshot}
        selected_agents = [
            agent for agent in [*killable, *dismissable] if agent.identity in live_ids
        ]
        cleanup_plan = killing_compat._plan_bulk_kill_cleanup_side_effects(
            selected_agents,
            agents_with_children_snapshot,
        )
        by_identity = {
            candidate.identity: candidate for candidate in agents_with_children_snapshot
        }
        seen_ids: set[AgentIdentity] = set()
        kill_items: list[BulkKillItem] = []
        failed_ids: set[AgentIdentity] = set()

        for planned_kill in cleanup_plan.kill_items:
            agent = by_identity.get(agent_identity_from_wire(planned_kill.identity))
            if agent is None or agent.identity not in live_ids:
                continue
            if agent.identity in seen_ids:
                continue
            kind = cast(KillKind, planned_kill.kind)
            if kind != "monitor" and agent.pid is not None:
                if not self._kill_agent_process_group(agent):  # type: ignore[attr-defined]
                    failed_ids.add(agent.identity)
                    continue
            identities = self._collect_immediate_kill_identities(agent)  # type: ignore[attr-defined]
            seen_ids.update(identities)
            kill_items.append(
                BulkKillItem(agent=agent, kind=kind, identities=identities)
            )

        dismiss_candidates = [
            a
            for a in dismissable
            if a.identity in live_ids
            and a.identity not in seen_ids
            and a.identity not in failed_ids
        ]
        if failed_ids:
            cleanup_plan = killing_compat._plan_bulk_kill_cleanup_side_effects(
                [item.agent for item in kill_items] + dismiss_candidates,
                agents_with_children_snapshot,
            )
        dismissed_ids = dismissed_identities_from_plan(cleanup_plan) - failed_ids
        # Union with the confirmed modal set so a planner miss cannot leave a
        # row on screen. Rows contributed only by the union get index-only
        # dismissal; the plan remains the source of truth for richer side
        # effects (bundle saves, artifact deletes, workspace releases,
        # notification dismissals).
        dismissed_ids |= self._collect_dismissal_identities(dismiss_candidates)  # type: ignore[attr-defined]
        recent_group = build_recent_dismissed_agent_group(
            agents_for_recent_group(dismissed_ids, agents_with_children_snapshot)
        )
        cache_recent_dismissed_agent_group(self, recent_group)

        killed_ids: set[AgentIdentity] = set()
        for item in kill_items:
            killed_ids.update(item.identities)

        for identity in dismissed_ids:
            self._agent_status_overrides.pop(identity, None)  # type: ignore[attr-defined]
            self._agent_pre_question_status.pop(identity, None)  # type: ignore[attr-defined]
        self._dismissed_agents.update(dismissed_ids)
        self._append_dismissed_agent_objects(dismiss_candidates, dismissed_ids)  # type: ignore[attr-defined]

        removed_ids = killed_ids | dismissed_ids
        self._reset_marked_agents()  # type: ignore[attr-defined]
        self._apply_killed_agents_in_memory(removed_ids)  # type: ignore[attr-defined]

        killed_count = len(kill_items)
        dismissed_count = len(dismiss_candidates)
        if killed_count or dismissed_count:
            self._notify_after_refresh(  # type: ignore[attr-defined]
                killing_compat._bulk_kill_summary(killed_count, dismissed_count)
            )

        if kill_items or dismiss_candidates:
            from ....dismissed_agents import snapshot_dismissed_agents

            self._submit_bulk_kill_persistence_proc(  # type: ignore[attr-defined]
                kill_items,
                dismiss_candidates,
                snapshot_dismissed_agents(self._dismissed_agents),
                agents_with_children_snapshot,
                cleanup_plan,
                recent_group,
                on_settled=on_settled,
            )
        elif on_settled is not None:
            on_settled()
        log.debug(
            "bulk agent kill immediate stage: killed=%d dismissed=%d elapsed=%.3fs",
            killed_count,
            dismissed_count,
            time.perf_counter() - started,
        )
        return bool(kill_items or dismiss_candidates)
