"""Optimistic UI flow for single and bulk TUI agent kills."""

from __future__ import annotations

import logging
import time
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
        self, agent: Agent, cleanup_plan: AgentCleanupPlanWire | None = None
    ) -> None:
        """Perform the actual agent kill after confirmation."""
        started = time.perf_counter()
        kind: KillKind | None
        if cleanup_plan is not None and cleanup_plan.kill_items:
            kind = cast(KillKind, cleanup_plan.kill_items[0].kind)
        else:
            kind = self._classify_kill_kind(agent)  # type: ignore[attr-defined]
        if kind is None:
            self.notify(  # type: ignore[attr-defined]
                f"Unknown agent type: {agent.agent_type}", severity="error"
            )
            return

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

        signaled: set[AgentIdentity] = set()
        signal_failed = False
        for target in kill_targets:
            if target.identity in signaled:
                continue
            signaled.add(target.identity)
            if target.pid is not None and not self._kill_agent_process_group(target):  # type: ignore[attr-defined]
                signal_failed = True
        if signal_failed:
            return
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
        )
        log.debug(
            "agent kill immediate stage: kind=%s identity=%s elapsed=%.3fs",
            kind,
            agent.identity,
            time.perf_counter() - started,
        )

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        """Kill/dismiss marked agents as one optimistic UI transaction."""
        from . import _killing as killing_compat

        started = time.perf_counter()
        dismissable = dismissable or []
        agents_with_children_snapshot = list(self._agents_with_children)
        live_ids = {a.identity for a in agents_with_children_snapshot}
        seen_ids: set[AgentIdentity] = set()
        kill_items: list[BulkKillItem] = []
        failed_ids: set[AgentIdentity] = set()

        for agent in killable:
            if agent.identity not in live_ids or agent.identity in seen_ids:
                continue
            kind = self._classify_kill_kind(agent)  # type: ignore[attr-defined]
            if kind is None:
                self.notify(  # type: ignore[attr-defined]
                    f"Unknown agent type: {agent.agent_type}", severity="error"
                )
                failed_ids.add(agent.identity)
                continue
            cascade_targets = [
                agent,
                *clan_members_for_container(
                    agent,
                    agents_with_children_snapshot,
                ),
            ]
            signal_failed = False
            for target in cascade_targets:
                if target.pid is None:
                    continue
                kill_succeeded = self._kill_agent_process_group(target)  # type: ignore[attr-defined]
                if not kill_succeeded:
                    signal_failed = True
            if signal_failed:
                failed_ids.update(target.identity for target in cascade_targets)
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
        cleanup_plan = killing_compat._plan_bulk_kill_cleanup_side_effects(
            [item.agent for item in kill_items] + dismiss_candidates,
            agents_with_children_snapshot,
        )
        dismissed_ids = dismissed_identities_from_plan(cleanup_plan)
        if not dismissed_ids:
            dismissed_ids = self._collect_dismissal_identities(dismiss_candidates)  # type: ignore[attr-defined]
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
            )
        log.debug(
            "bulk agent kill immediate stage: killed=%d dismissed=%d elapsed=%.3fs",
            killed_count,
            dismissed_count,
            time.perf_counter() - started,
        )
