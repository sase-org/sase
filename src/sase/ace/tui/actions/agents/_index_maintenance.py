"""Deferred artifact-index dismissed-projection maintenance for agents."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index_report,
)

from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from ._loading_state import AgentIdentity, AgentLoadingStateMixin

log = logging.getLogger(__name__)

_ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S = 3600.0
_ArtifactIndexMaintenanceRequest = tuple[
    set[AgentIdentity],
    set[AgentIdentity] | None,
    bool,
    str,
]


def _identity_snapshot(
    identities: Iterable[tuple[Any, str, str | None]] | None,
) -> set[AgentIdentity] | None:
    if identities is None:
        return None
    return {
        (agent_type, cl_name, raw_suffix)
        for agent_type, cl_name, raw_suffix in identities
    }


class AgentIndexMaintenanceMixin(AgentLoadingStateMixin):
    """Coalesce dismissed-projection syncs and run them off the event loop."""

    def _schedule_artifact_index_maintenance(
        self,
        *,
        dismissed: Iterable[tuple[Any, str, str | None]],
        added: Iterable[tuple[Any, str, str | None]] | None = None,
        force: bool = False,
        source: str = "unknown",
    ) -> None:
        """Queue dismissed-projection sync work without blocking the UI thread."""
        dismissed_snapshot = _identity_snapshot(dismissed)
        assert dismissed_snapshot is not None
        added_snapshot = _identity_snapshot(added)
        existing = self._artifact_index_maintenance_pending_request
        if existing is not None:
            force = force or existing[2]
        self._artifact_index_maintenance_pending_request = (
            dismissed_snapshot,
            added_snapshot,
            force,
            source,
        )
        if getattr(self, "_artifact_index_schema_bypass", False):
            self._artifact_index_maintenance_pending = True
            return
        if self._artifact_index_maintenance_running:
            self._artifact_index_maintenance_pending = True
            return
        self._artifact_index_maintenance_running = True
        self._spawn_artifact_index_maintenance_task()

    def _spawn_artifact_index_maintenance_task(self) -> None:
        """Run index maintenance without occupying Textual's message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_artifact_index_maintenance(),
            name="sase-agents-index-maintenance",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._artifact_index_maintenance_running = False

    def _resume_artifact_index_maintenance_after_schema_rebuild(self) -> None:
        """Run the latest request deferred while the schema rebuild held the lock."""
        if self._artifact_index_maintenance_running:
            return
        if self._artifact_index_maintenance_pending_request is None:
            self._artifact_index_maintenance_pending = False
            return
        self._artifact_index_maintenance_pending = False
        self._artifact_index_maintenance_running = True
        self._spawn_artifact_index_maintenance_task()

    async def _run_artifact_index_maintenance(self) -> None:
        """Run the latest queued maintenance request in a worker thread."""
        if self._nav_gate.is_navigating():
            delay = self._nav_gate.time_until_idle() + 0.05
            self.set_timer(  # type: ignore[attr-defined]
                delay,
                self._spawn_artifact_index_maintenance_task,
            )
            return

        request = self._artifact_index_maintenance_pending_request
        self._artifact_index_maintenance_pending_request = None
        self._artifact_index_maintenance_pending = False
        if request is None:
            self._artifact_index_maintenance_running = False
            return

        dismissed_snapshot, added_snapshot, force, source = request
        run_terminalize = self._should_run_active_tier_terminalize()
        try:
            with tui_trace(
                "agents.artifact_index_maintenance",
                dismissed=len(dismissed_snapshot),
                added=0 if added_snapshot is None else len(added_snapshot),
                force=force,
                source=source,
                terminalize=run_terminalize,
            ):
                await asyncio.to_thread(
                    sync_dismissed_agent_artifact_index_report,
                    dismissed_snapshot,
                    added=added_snapshot,
                    force=force,
                    run_active_tier_maintenance=run_terminalize,
                )
            if run_terminalize:
                self._artifact_index_maintenance_last_mono = time.monotonic()
        except Exception:
            log.exception("Artifact index maintenance failed")
        finally:
            has_followup = self._artifact_index_maintenance_pending_request is not None
            self._artifact_index_maintenance_running = False
            if has_followup:
                self._artifact_index_maintenance_pending = False
                self._artifact_index_maintenance_running = True
                self._spawn_artifact_index_maintenance_task()

    def _should_run_active_tier_terminalize(self) -> bool:
        """Return whether apply-triggered maintenance may terminalize now."""
        last = self._artifact_index_maintenance_last_mono
        if last <= 0.0:
            return False
        return (time.monotonic() - last) >= _ACTIVE_TIER_MAINTENANCE_MIN_INTERVAL_S
