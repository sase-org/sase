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

    from sase.core.query_profile_corpus_facade import ArtifactQueryIndex

    from .beads_filtering import BeadFilterIndex
    from .query_session import ArtifactQuerySession
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
        _filter_index: BeadFilterIndex | None
        _filter_index_source_key: tuple[object, ...] | None
        _query_index: ArtifactQueryIndex | None
        _query_session: ArtifactQuerySession

        @property
        def artifacts_active(self) -> bool: ...

        def _refresh_options(
            self,
            *,
            preferred_id: str | None = None,
            update_detail: bool = True,
        ) -> None: ...

    def _reindex_for_stranded_reports(self) -> bool:
        """Rebuild the Beads filter/query indexes for new stranded verdicts.

        The filter index is cached by snapshot source key plus the stranded
        report token, so without a rebuild ``status:stranded`` would keep
        serving stale rows after the warmup worker replaces a report.
        Returns True when the indexes were actually rebuilt.
        """
        from .query_rows import build_beads_query_index

        snapshot = self._snapshot
        profile = getattr(self, "_query_profile", None)
        index = getattr(self, "_query_index", None)
        session = getattr(self, "_query_session", None)
        if snapshot is None or profile is None or index is None or session is None:
            return False
        if snapshot.project != self.project_scope:
            return False
        filter_index, query_index = build_beads_query_index(
            snapshot,
            pane_id=profile.pane_id,
            generation=index.generation,
            profile=profile,
        )
        session.clear()
        self._filter_index = filter_index
        self._filter_index_source_key = filter_index.source_key
        self._query_index = query_index
        return True

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
            from .beads_filtering import beads_filter_source_key

            reindexed = False
            if beads_filter_source_key(current) != getattr(
                self, "_filter_index_source_key", None
            ):
                reindexed = self._reindex_for_stranded_reports()
            signature = beads_stranded_signature(current)
            if signature != self._stranded_signature:
                self._stranded_signature = signature
                self._refresh_options()
            elif reindexed:
                # The stranded token changed without changing displayed facts
                # (for example a first warmup that stored an empty report):
                # the reindex already rebuilt the rows, so repaint once.
                self._refresh_options()
        finally:
            self._stranded_running = False
            pending, self._stranded_pending = self._stranded_pending, False
            if pending and self.is_mounted:
                self._schedule_stranded_refresh()
