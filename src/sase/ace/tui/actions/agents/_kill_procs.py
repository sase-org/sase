"""Tracked background proc submission for TUI agent kills."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ._cleanup_procs import CleanupProcOutcome
from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire

log = logging.getLogger(__name__)


class AgentKillPersistenceProcMixin:
    """Mixin for submitting kill persistence as tracked cleanup procs."""

    _agents_with_children: list[Agent]
    _dismissed_agents: set[AgentIdentity]
    _kill_persistence_inflight: set[AgentIdentity]

    def _submit_bulk_kill_persistence_proc(
        self,
        kill_items: list[BulkKillItem],
        dismissable: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        recent_group: SavedAgentGroupWire | None = None,
    ) -> None:
        """Submit bulk kill/dismiss persistence as a tracked background proc."""
        from . import _killing as killing_compat

        inflight = {item.agent.identity for item in kill_items}
        if inflight & self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.update(inflight)

        killed_count = len(kill_items)
        dismissed_count = len(dismissable)

        def _worker() -> CleanupProcOutcome:
            started = time.perf_counter()
            register_expected_deletion = None
            if hasattr(self, "_expected_agent_artifact_deletions_lock"):
                register_expected_deletion = (
                    self._register_expected_agent_artifact_deletion  # type: ignore[attr-defined]
                )
            try:
                if register_expected_deletion is None:
                    killing_compat._persist_bulk_kill_transaction(
                        kill_items,
                        dismissable,
                        dismissed_snapshot,
                        agents_with_children_snapshot,
                        cleanup_plan,
                        recent_group,
                    )
                else:
                    killing_compat._persist_bulk_kill_transaction(
                        kill_items,
                        dismissable,
                        dismissed_snapshot,
                        agents_with_children_snapshot,
                        cleanup_plan,
                        recent_group,
                        register_expected_deletion=register_expected_deletion,
                    )
            except Exception as exc:
                return CleanupProcOutcome(
                    message=f"Bulk kill cleanup failed: {exc}",
                    severity="error",
                    notify=True,
                    schedule_agents_refresh_source="kill_error_recovery",
                )
            finally:
                self._kill_persistence_inflight.difference_update(inflight)
                log.debug(
                    "bulk agent kill persistence: killed=%d dismissed=%d elapsed=%.3fs",
                    killed_count,
                    dismissed_count,
                    time.perf_counter() - started,
                )
            return CleanupProcOutcome(
                message=killing_compat._bulk_kill_summary(
                    killed_count, dismissed_count
                ),
                refresh_notifications=True,
            )

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="kill",
            display_name=killing_compat._bulk_kill_task_display_name(
                killed_count, dismissed_count
            ),
            cl_name="",
            project_file="",
            proc_callable=_worker,
        ):
            self._kill_persistence_inflight.difference_update(inflight)

    def _submit_kill_persistence_proc(
        self,
        agent: Agent,
        kind: KillKind,
        agents_with_children_snapshot: list[Agent] | None = None,
        dismissed_snapshot: set[AgentIdentity] | None = None,
        cleanup_plan: AgentCleanupPlanWire | None = None,
    ) -> None:
        """Submit single-agent kill persistence as a tracked background proc."""
        identity = agent.identity
        if identity in self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.add(identity)

        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        if dismissed_snapshot is None:
            from ....dismissed_agents import snapshot_dismissed_agents

            dismissed_snapshot = snapshot_dismissed_agents(self._dismissed_agents)
        related_agents = self._agents_related_to_kill(  # type: ignore[attr-defined]
            agent, agents_with_children_snapshot
        )

        def _worker() -> CleanupProcOutcome:
            from . import _killing as killing_compat

            started = time.perf_counter()
            register_expected_deletion = None
            if hasattr(self, "_expected_agent_artifact_deletions_lock"):
                register_expected_deletion = (
                    self._register_expected_agent_artifact_deletion  # type: ignore[attr-defined]
                )
            try:
                if register_expected_deletion is None:
                    killing_compat._persist_single_kill_transaction(
                        agent,
                        kind,
                        agents_with_children_snapshot,
                        dismissed_snapshot,
                        cleanup_plan,
                        related_agents,
                    )
                else:
                    killing_compat._persist_single_kill_transaction(
                        agent,
                        kind,
                        agents_with_children_snapshot,
                        dismissed_snapshot,
                        cleanup_plan,
                        related_agents,
                        register_expected_deletion=register_expected_deletion,
                    )
            except Exception as exc:
                return CleanupProcOutcome(
                    message=f"Kill cleanup failed for {agent.display_name}: {exc}",
                    severity="error",
                    notify=True,
                    schedule_agents_refresh_source="kill_error_recovery",
                )
            finally:
                self._kill_persistence_inflight.discard(identity)
                log.debug(
                    "agent kill persistence: kind=%s identity=%s elapsed=%.3fs",
                    kind,
                    identity,
                    time.perf_counter() - started,
                )
            return CleanupProcOutcome(
                message=f"Killed {agent.display_name}",
                refresh_notifications=True,
            )

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="kill",
            display_name=f"kill {agent.display_name}",
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            proc_callable=_worker,
        ):
            self._kill_persistence_inflight.discard(identity)
