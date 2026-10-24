"""Deferred, coalesced stranded-report refresh for the Beads pane."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ...models.agent_stranded import warm_stranded_work_reports
from ...util.pump_tasks import spawn_pump_free_task
from .beads_data_models import BeadsSnapshot
from .beads_stranded import beads_stranded_signature

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class BeadsStrandedRefreshMixin(_MixinBase):
    _snapshot: BeadsSnapshot | None
    project_scope: str | None
    _stranded_running: bool = False
    _stranded_pending: bool = False
    _stranded_force: bool = False
    _stranded_signature: tuple[object, ...] = ()

    if TYPE_CHECKING:

        @property
        def artifacts_active(self) -> bool: ...

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

    def _schedule_stranded_refresh(self, *, force: bool = False) -> None:
        """Keep store reads out of first paint and Textual's message pump."""
        if not self.artifacts_active or self._snapshot is None:
            return
        self._stranded_force |= force
        if self._stranded_running:
            self._stranded_pending = True
            return
        self._stranded_running = True
        task = spawn_pump_free_task(
            self,
            self._refresh_stranded(),
            name="sase-artifacts-beads-stranded-refresh",
            registry_attr="_beads_stranded_refresh_tasks",
        )
        if task is None:
            self._stranded_running = False

    async def _refresh_stranded(self) -> None:
        try:
            await asyncio.sleep(0)
            snapshot = self._snapshot
            if (
                not self.artifacts_active
                or snapshot is None
                or snapshot.project != self.project_scope
            ):
                return
            force, self._stranded_force = self._stranded_force, False
            await asyncio.to_thread(
                warm_stranded_work_reports, snapshot.projects, force=force
            )
            # The selection, scope, and inventory may have changed during I/O.
            current = self._snapshot
            if (
                not self.artifacts_active
                or current is None
                or current.project != self.project_scope
                or current.projects != snapshot.projects
            ):
                return
            signature = beads_stranded_signature(current)
            if signature != self._stranded_signature:
                self._stranded_signature = signature
                self._refresh_options()
        finally:
            self._stranded_running = False
            pending, self._stranded_pending = self._stranded_pending, False
            if pending and self.is_mounted:
                self._schedule_stranded_refresh()
