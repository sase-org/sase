"""Shared support for loading agent state from disk."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from ...util.pump_tasks import spawn_pump_free_task
from ...util.trace import tui_trace
from . import _loading_helpers
from ._loading_compute import (
    _CLEANED_ARTIFACT_DIRS,
    compute_apply_loaded_agents,
    compute_loader_cleanup,
)
from ._loading_state import AgentLoadingStateMixin

_SLOW_LOADER_STAGE_THRESHOLD_SECONDS = 2.0

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchIndex
    from ...models.agent_loader import AgentLoadState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalDismissalMergeResult:
    file_signature: tuple[int, int] | None
    on_disk_identities: set[tuple[AgentType, str, str | None]]
    new_external_identities: set[tuple[AgentType, str, str | None]]


def compute_external_dismissal_merge(
    *,
    cached_signature: tuple[int, int] | None,
    cached_on_disk_identities: set[tuple[AgentType, str, str | None]],
    cache_initialized: bool,
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
) -> ExternalDismissalMergeResult | None:
    from ....dismissed_agents import (
        dismissed_agents_file_signature,
        load_dismissed_agents,
    )

    file_signature = dismissed_agents_file_signature()
    if cache_initialized and file_signature == cached_signature:
        return None

    try:
        on_disk = load_dismissed_agents()
    except Exception:
        return None

    if cache_initialized:
        new_external = on_disk - cached_on_disk_identities
    else:
        new_external = on_disk - dismissed_snapshot

    return ExternalDismissalMergeResult(
        file_signature=file_signature,
        on_disk_identities=set(on_disk),
        new_external_identities=new_external,
    )


def _resolve_external_dismissal_merge() -> Callable[..., Any]:
    """Resolve through the disk facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading_disk")
    merge = getattr(
        facade,
        "_compute_external_dismissal_merge",
        compute_external_dismissal_merge,
    )
    return cast(Callable[..., Any], merge)


def _resolve_loader_cleanup() -> Callable[..., Any]:
    """Resolve through the disk facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading_disk")
    cleanup = getattr(facade, "compute_loader_cleanup", compute_loader_cleanup)
    return cast(Callable[..., Any], cleanup)


class AgentLoadingDiskSupportMixin(AgentLoadingStateMixin):
    """Search indexing, dismissal merging, cleanup, and load telemetry."""

    def _prepare_agent_content_search_index_sync(
        self,
        agents: list[Agent],
    ) -> AgentContentSearchIndex | None:
        """Build a content index outside finalization for sync load callers."""
        if not getattr(self, "_agent_search_query", ""):
            self._agent_content_search_index = None
            return None
        for agent in agents:
            _loading_helpers.hydrate_agent_attempt_history(agent)
        worker_cache = self._agent_content_search_cache.fork()
        index = worker_cache.build_index(agents)
        self._agent_content_search_cache.merge(worker_cache)
        self._agent_content_search_index = index
        return index

    async def _prepare_agent_content_search_index_async(
        self,
        agents: list[Agent],
    ) -> AgentContentSearchIndex | None:
        """Build a content index in a worker thread for async load callers."""
        import asyncio

        if not getattr(self, "_agent_search_query", ""):
            self._agent_content_search_index = None
            return None

        def hydrate_attempts() -> None:
            for agent in agents:
                _loading_helpers.hydrate_agent_attempt_history(agent)

        await asyncio.to_thread(hydrate_attempts)
        worker_cache = self._agent_content_search_cache.fork()
        index = await asyncio.to_thread(worker_cache.build_index, agents)
        if not getattr(self, "_agent_search_query", ""):
            return None
        self._agent_content_search_cache.merge(worker_cache)
        self._agent_content_search_index = index
        return index

    def _external_dismissal_merge_result(
        self,
        dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    ) -> ExternalDismissalMergeResult | None:
        return _resolve_external_dismissal_merge()(
            cached_signature=getattr(self, "_dismissed_agents_disk_signature", None),
            cached_on_disk_identities=set(
                getattr(self, "_dismissed_agents_disk_identities", set())
            ),
            cache_initialized=bool(
                getattr(self, "_dismissed_agents_disk_signature_initialized", False)
            ),
            dismissed_snapshot=dismissed_snapshot,
        )

    def _apply_external_dismissal_merge(
        self, result: ExternalDismissalMergeResult | None
    ) -> None:
        if result is None:
            return
        self._dismissed_agents_disk_signature = result.file_signature
        self._dismissed_agents_disk_identities = set(result.on_disk_identities)
        self._dismissed_agents_disk_signature_initialized = True
        if result.new_external_identities:
            self._dismissed_agents.update(result.new_external_identities)

    def _merge_external_dismissals(self) -> None:
        """Union on-disk dismissed-agent identities into the in-memory set.

        External processes (Telegram kill, ``sase agent kill``, gchat) write
        to ``~/.sase/dismissed_agents.json`` directly via
        :func:`sase.agent.running.kill_named_agent`. Without this merge a
        long-lived TUI would never observe those entries on its next refresh
        and would re-classify the killed agent as FAILED.

        Only unions in new entries — never drops in-memory entries that
        haven't been flushed to disk yet (the optimistic kill flow updates
        memory first and persists asynchronously).
        """
        result = self._external_dismissal_merge_result(set(self._dismissed_agents))
        self._apply_external_dismissal_merge(result)

    def _schedule_loader_cleanup(
        self,
        dismissed_snapshot: set[tuple[AgentType, str, str | None]],
        dismissed_from_loader: list[Agent],
        *,
        source: str,
        load_kind: str,
    ) -> None:
        """Queue one latest-wins self-healing pass after rows are applied."""
        if not dismissed_snapshot and not dismissed_from_loader:
            return
        self._loader_cleanup_pending_request = (
            set(dismissed_snapshot),
            list(dismissed_from_loader),
            source,
            load_kind,
        )
        if getattr(self, "_loader_cleanup_running", False):
            self._loader_cleanup_pending = True
            return
        self._loader_cleanup_running = True
        self._loader_cleanup_pending = False
        self._spawn_loader_cleanup_task()

    def _spawn_loader_cleanup_task(self) -> None:
        """Run loader cleanup outside Textual's serial message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_loader_cleanup(),
            name="sase-agents-loader-cleanup",
            registry_attr="_loader_cleanup_async_tasks",
        )
        if task is None:
            self._loader_cleanup_running = False

    async def _run_loader_cleanup(self) -> None:
        """Run one cleanup request and coalesce any burst into one trailing pass."""
        import asyncio

        nav_gate = getattr(self, "_nav_gate", None)
        if nav_gate is not None and nav_gate.is_navigating():
            delay = nav_gate.time_until_idle() + 0.05
            self.set_timer(delay, self._spawn_loader_cleanup_task)  # type: ignore[attr-defined]
            return

        request = getattr(self, "_loader_cleanup_pending_request", None)
        self._loader_cleanup_pending_request = None
        self._loader_cleanup_pending = False
        if request is None:
            self._loader_cleanup_running = False
            return

        dismissed_snapshot, dismissed_from_loader, source, load_kind = request
        cleanup_start = time.perf_counter()
        try:
            orphaned, cleaned_dirs = await asyncio.to_thread(
                _resolve_loader_cleanup(),
                dismissed_snapshot,
                dismissed_from_loader,
            )
            cleanup_elapsed = time.perf_counter() - cleanup_start
            if orphaned:
                removed = set(self._dismissed_agents) & orphaned
                if removed:
                    self._dismissed_agents -= removed
                    from ....dismissed_agents import (
                        save_dismissed_agents,
                        snapshot_dismissed_agents,
                    )

                    snapshot = snapshot_dismissed_agents(self._dismissed_agents)
                    if await asyncio.to_thread(save_dismissed_agents, snapshot):
                        self._schedule_artifact_index_maintenance(
                            dismissed=set(self._dismissed_agents),
                            force=True,
                            source="loader_cleanup",
                        )
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
            log.debug(
                "agents loader cleanup: elapsed=%.3fs orphaned=%d cleaned=%d",
                cleanup_elapsed,
                len(orphaned),
                len(cleaned_dirs),
            )
            self._record_slow_loader_stages(
                source=source,
                load_kind=load_kind,
                stages={"cleanup": cleanup_elapsed},
                orphaned=len(orphaned),
                cleaned=len(cleaned_dirs),
            )
        except Exception:
            log.exception("Agents loader cleanup failed")
        finally:
            has_followup = self._loader_cleanup_pending_request is not None
            self._loader_cleanup_running = False
            if has_followup:
                self._loader_cleanup_pending = False
                self._loader_cleanup_running = True
                self._spawn_loader_cleanup_task()

    def _record_slow_loader_stages(
        self,
        *,
        source: str,
        load_kind: str,
        stages: dict[str, float],
        **fields: Any,
    ) -> None:
        """Persist slow-stage timings without putting log I/O on the UI loop."""
        import asyncio

        slow_stages = sorted(
            name
            for name, elapsed in stages.items()
            if elapsed >= _SLOW_LOADER_STAGE_THRESHOLD_SECONDS
        )
        if not slow_stages:
            return
        from sase.logs import log_tui_agent_load

        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "tui_agent_load_slow",
            "pid": os.getpid(),
            "source": source,
            "load_kind": load_kind,
            "threshold_seconds": _SLOW_LOADER_STAGE_THRESHOLD_SECONDS,
            "slow_stages": slow_stages,
            "stages_seconds": {
                name: round(elapsed, 6) for name, elapsed in stages.items()
            },
        }
        record.update(fields)
        spawn_pump_free_task(
            self,
            asyncio.to_thread(log_tui_agent_load, record),
            name="sase-agents-loader-telemetry",
            registry_attr="_loader_cleanup_async_tasks",
        )

    def _apply_loaded_agents(
        self,
        all_agents: list[Agent],
        dismissed_from_loader: list[Agent],
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        configured_runner_limit: int | None = None,
    ) -> None:
        """Apply loaded agent data to app state (main thread only).

        Sync callers own the cleanup pass. The async path prepares its data
        on a worker thread and calls ``_apply_loaded_agents_prepared`` directly.
        """
        if not self._agents_loading:
            orphaned, cleaned_dirs = _resolve_loader_cleanup()(
                set(self._dismissed_agents), dismissed_from_loader
            )
            if orphaned:
                self._dismissed_agents -= orphaned
            if cleaned_dirs:
                _CLEANED_ARTIFACT_DIRS.update(cleaned_dirs)
        else:
            orphaned = set()

        with tui_trace(
            "agents.worker_prep",
            agents=len(all_agents),
            dismissed=len(dismissed_from_loader),
        ):
            prep = compute_apply_loaded_agents(
                all_agents,
                dismissed_from_loader,
                set(self._dismissed_agents),
                bool(self.hide_non_run_agents),
            )
        self._prepare_agent_content_search_index_sync(prep.filtered_agents)
        self._apply_loaded_agents_prepared(
            prep,
            on_agents_tab=on_agents_tab,
            selected_identity=selected_identity,
            load_state=load_state,
            persist_dismissed_changes=bool(orphaned)
            or bool(prep.recovered_bundle_identities)
            or bool(prep.auto_dismissed_identities),
            dismissed_changes_include_removals=bool(orphaned),
            configured_runner_limit=configured_runner_limit,
        )
