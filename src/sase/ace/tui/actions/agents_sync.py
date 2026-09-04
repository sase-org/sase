"""Tracked agents-sidecar publication sync for ACE."""

from __future__ import annotations

from sase.agents_sync import sync_agents
from sase.agents_sync.models import SyncOutcome

from ..agents_sync_format import (
    agents_sync_outcome_line,
    summarize_agents_sync_outcomes,
)
from ..session_proc_reporter import SessionProcReporter
from .proc_actions import TrackedProcCompletion, TrackedProcResult


class AgentsSyncActionsMixin:
    """Own the ACE manual agents-sidecar publication sync."""

    def action_sync_agents(self) -> None:
        """Submit publication/reconciliation of every enabled agents repo."""

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[tuple[SyncOutcome, ...]]:
            reporter.phase("Publishing and reconciling agent hoods")
            outcomes = sync_agents()
            reporter.section("Agents repository results")
            for outcome in outcomes:
                reporter.log(agents_sync_outcome_line(outcome), stream="result")
            message = f"Agent hoods: {summarize_agents_sync_outcomes(outcomes)}"
            failed = any(outcome.error for outcome in outcomes)
            return TrackedProcResult(
                success=not failed,
                message=message,
                payload=outcomes,
                error=message if failed else None,
            )

        def on_complete(
            _completion: TrackedProcCompletion[tuple[SyncOutcome, ...]],
        ) -> None:
            self._schedule_agents_refresh_after_sync(source="agents_full_sync")

        submit = getattr(self, "_submit_session_worker", None)
        if not callable(submit):
            return
        submit(
            "agents-sync",
            task,
            display_name="publish and reconcile agent hoods",
            cl_name="agent hoods",
            dedup_key="agents-sync",
            exclusive_scopes=("agents-sync",),
            duplicate_message="An agents-sidecar publication sync is already running.",
            on_complete=on_complete,
        )

    def _schedule_agents_refresh_after_sync(self, *, source: str) -> None:
        """Use the existing coalesced agent-list reload after sync mutations."""
        refresh = getattr(self, "_schedule_agents_async_refresh", None)
        if callable(refresh):
            refresh(source=source)


__all__ = ["AgentsSyncActionsMixin"]
