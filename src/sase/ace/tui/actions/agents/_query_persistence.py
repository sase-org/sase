"""Agents-tab committed-query restore and persistence lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models.agent_query_persistence import (
        AgentQueryDialect,
        AgentQueryLoadResult,
        AgentQuerySnapshot,
    )
    from ...models.agent_live_query_engine import AgentsLiveQueryFacade

log = logging.getLogger(__name__)

_FLUSH_TIMEOUT_SECONDS = 2.0
_SAVE_WARNING_INTERVAL_SECONDS = 5 * 60


class AgentQueryPersistenceMixin:
    """Restore, remember, save, and flush the committed Agents query."""

    _agent_search_query: str
    _agent_search_query_seeded: bool
    _agent_search_query_seed_attempted: bool
    _agent_search_query_generation: int
    _agent_query_cache: tuple[str, QueryExpr | None] | None
    _agent_query_parse_error: str | None
    _agents_live_query_facade: AgentsLiveQueryFacade | None
    _agents_committed_match_count: tuple[int, int] | None
    _agents_query_restore_attempted: bool
    _agents_query_restore_task: asyncio.Task[AgentQueryLoadResult] | None
    _agents_query_restore_warning_shown: bool
    _agents_query_durable_snapshot: AgentQuerySnapshot | None
    _agents_query_queued_snapshot: AgentQuerySnapshot | None
    _agents_query_save_generation: int
    _agents_query_completed_generation: int
    _agents_query_save_pending: tuple[int, AgentQuerySnapshot] | None
    _agents_query_dirty_snapshot: tuple[int, AgentQuerySnapshot] | None
    _agents_query_save_task: asyncio.Task[None] | None
    _agents_query_last_save_warning_mono: float

    def _ensure_agents_query_persistence_state(self) -> None:
        """Initialize fields for direct-mixin tests that bypass app startup."""
        defaults: tuple[tuple[str, object], ...] = (
            ("_agent_search_query_generation", 0),
            ("_agents_query_restore_attempted", False),
            ("_agents_query_restore_task", None),
            ("_agents_query_restore_warning_shown", False),
            ("_agents_query_durable_snapshot", None),
            ("_agents_query_queued_snapshot", None),
            ("_agents_query_save_generation", 0),
            ("_agents_query_completed_generation", 0),
            ("_agents_query_save_pending", None),
            ("_agents_query_dirty_snapshot", None),
            ("_agents_query_save_task", None),
            ("_agents_query_last_save_warning_mono", 0.0),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)

    def _active_agents_query_dialect(self) -> AgentQueryDialect:
        from ...models.agent_query_persistence import active_agent_query_dialect

        return active_agent_query_dialect()

    def _make_agents_query_snapshot(self, source: str) -> AgentQuerySnapshot:
        from ...models.agent_query_persistence import make_agent_query_snapshot

        return make_agent_query_snapshot(
            source,
            dialect=self._active_agents_query_dialect(),
        )

    def _clear_agents_query_runtime_cache(self) -> None:
        """Drop cached parse/facade state tied to the previous query string."""
        if hasattr(self, "_agent_query_cache"):
            self._agent_query_cache = None
        if hasattr(self, "_agent_query_parse_error"):
            self._agent_query_parse_error = None
        if hasattr(self, "_agents_live_query_facade"):
            self._agents_live_query_facade = None
        if hasattr(self, "_agents_committed_match_count"):
            self._agents_committed_match_count = None

    def _apply_agents_query_source_without_persisting(
        self,
        source: str,
        *,
        seeded: bool,
        settle_seed: bool,
    ) -> None:
        """Install a startup restore/seed query without writing it back."""
        normalized = "" if not source.strip() else source
        if normalized != (getattr(self, "_agent_search_query", "") or ""):
            self._agent_search_query_generation = (
                getattr(self, "_agent_search_query_generation", 0) + 1
            )
            self._clear_agents_query_runtime_cache()
        self._agent_search_query = normalized
        self._agent_search_query_seeded = seeded
        if settle_seed:
            self._agent_search_query_seed_attempted = True

    def _record_explicit_agents_query_commit(
        self,
        source: str,
    ) -> AgentQuerySnapshot:
        """Record a successful user query commit and enqueue persistence."""
        self._ensure_agents_query_persistence_state()
        snapshot = self._make_agents_query_snapshot(source)
        self._agent_search_query_generation += 1
        self._agent_search_query = snapshot.record.source
        self._agent_search_query_seeded = False
        self._agent_search_query_seed_attempted = True
        self._clear_agents_query_runtime_cache()
        self._queue_agents_query_snapshot(snapshot)
        return snapshot

    async def _restore_agents_query_once(self) -> bool:
        """One-shot async restore used by the startup Agents load."""
        self._ensure_agents_query_persistence_state()
        if self._agents_query_restore_attempted:
            return False

        generation = self._agent_search_query_generation
        task = self._agents_query_restore_task
        if task is None:
            active_dialect = self._active_agents_query_dialect()
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._load_agents_query_snapshot_now,
                    active_dialect,
                ),
                name="agents-query-restore",
            )
            self._agents_query_restore_task = task

        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Agents query restore failed")
            result = self._failed_agents_query_restore_result()
        finally:
            if task.done() and self._agents_query_restore_task is task:
                self._agents_query_restore_task = None
                self._agents_query_restore_attempted = True

        return self._apply_agents_query_restore_result(
            result,
            generation=generation,
        )

    def _load_agents_query_snapshot_now(
        self,
        active_dialect: AgentQueryDialect,
    ) -> AgentQueryLoadResult:
        from ...models.agent_query_persistence import load_agent_query_snapshot

        return load_agent_query_snapshot(active_dialect=active_dialect)

    def _failed_agents_query_restore_result(self) -> AgentQueryLoadResult:
        from ...models.agent_query_persistence import AgentQueryLoadResult

        return AgentQueryLoadResult(
            warning="Could not read the saved Agents query; submit a query to replace it."
        )

    def _apply_agents_query_restore_result(
        self,
        result: AgentQueryLoadResult,
        *,
        generation: int | None = None,
    ) -> bool:
        """Apply an explicitly loaded restore result without touching disk."""
        self._ensure_agents_query_persistence_state()
        if result.warning:
            self._notify_agents_query_restore_warning(result.warning)
        snapshot = result.snapshot
        if snapshot is None:
            return False
        expected = (
            self._agent_search_query_generation if generation is None else generation
        )
        if self._agent_search_query_generation != expected:
            return False
        if getattr(self, "_controlled_exit_started", False):
            return False

        self._agents_query_durable_snapshot = snapshot
        self._agents_query_queued_snapshot = snapshot
        self._apply_agents_query_source_without_persisting(
            snapshot.record.source,
            seeded=False,
            settle_seed=True,
        )
        return True

    def _notify_agents_query_restore_warning(self, message: str) -> None:
        if getattr(self, "_agents_query_restore_warning_shown", False):
            return
        self._agents_query_restore_warning_shown = True
        try:
            self.notify(message, severity="warning", timeout=12.0)  # type: ignore[attr-defined]
        except Exception:
            log.warning("Agents query restore warning: %s", message)

    def _queue_agents_query_snapshot(self, snapshot: AgentQuerySnapshot) -> None:
        self._ensure_agents_query_persistence_state()
        task = self._agents_query_save_task
        idle = task is None or task.done()
        if (
            snapshot == self._agents_query_durable_snapshot
            and self._agents_query_save_pending is None
            and self._agents_query_dirty_snapshot is None
            and idle
        ):
            return
        if self._agents_query_save_pending is not None:
            _generation, pending_snapshot = self._agents_query_save_pending
            if pending_snapshot == snapshot:
                return

        generation = self._agents_query_save_generation + 1
        self._agents_query_save_generation = generation
        self._agents_query_save_pending = (generation, snapshot)
        self._agents_query_dirty_snapshot = (generation, snapshot)
        self._agents_query_queued_snapshot = snapshot
        self._start_agents_query_writer()

    def _start_agents_query_writer(self) -> None:
        self._ensure_agents_query_persistence_state()
        task = self._agents_query_save_task
        if task is not None and not task.done():
            return
        if self._agents_query_save_pending is None:
            return

        from ...util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            self,
            self._run_agents_query_save_loop(),
            name="agents-query-save",
            registry_attr="_pump_free_async_tasks",
        )
        if task is not None:
            self._agents_query_save_task = task

    async def _run_agents_query_save_loop(self) -> None:
        """Write one generation at a time, coalescing to the latest pending."""
        restart = True
        try:
            while True:
                pending = self._agents_query_save_pending
                self._agents_query_save_pending = None
                if pending is None:
                    break
                generation, snapshot = pending
                try:
                    await asyncio.to_thread(
                        self._save_agents_query_snapshot_now, snapshot
                    )
                except asyncio.CancelledError:
                    restart = False
                    raise
                except Exception:
                    if (
                        generation == self._agents_query_save_generation
                        and self._agents_query_save_pending is None
                    ):
                        self._agents_query_queued_snapshot = None
                    self._warn_agents_query_save_failed()
                else:
                    self._agents_query_durable_snapshot = snapshot
                    dirty = self._agents_query_dirty_snapshot
                    if dirty is not None and dirty[0] <= generation:
                        self._agents_query_dirty_snapshot = None
                    self._agents_query_queued_snapshot = snapshot
                finally:
                    self._agents_query_completed_generation = max(
                        self._agents_query_completed_generation,
                        generation,
                    )
        finally:
            self._agents_query_save_task = None
            if restart and self._agents_query_save_pending is not None:
                self._start_agents_query_writer()

    def _save_agents_query_snapshot_now(self, snapshot: AgentQuerySnapshot) -> None:
        from ...models.agent_query_persistence import save_agent_query_snapshot

        save_agent_query_snapshot(snapshot)

    def _warn_agents_query_save_failed(self) -> None:
        now = time.monotonic()
        last = getattr(self, "_agents_query_last_save_warning_mono", 0.0)
        if last and now - last < _SAVE_WARNING_INTERVAL_SECONDS:
            log.warning("Agents query save failed; suppressing repeated notification")
            return
        self._agents_query_last_save_warning_mono = now
        message = "Unable to save Agents query; it will stay active for this session."
        try:
            self.notify(message, severity="warning", timeout=10.0)  # type: ignore[attr-defined]
        except Exception:
            log.warning(message)

    async def _flush_agents_query_state(self) -> None:
        """Await and retry the latest dirty query snapshot during controlled exit."""
        self._ensure_agents_query_persistence_state()

        async def _await_generation(target: int) -> None:
            while self._agents_query_completed_generation < target:
                task = self._agents_query_save_task
                if task is None:
                    if self._agents_query_save_pending is None:
                        break
                    self._start_agents_query_writer()
                    await asyncio.sleep(0)
                    continue
                await asyncio.shield(task)

        async def _flush() -> None:
            await _await_generation(self._agents_query_save_generation)
            dirty = self._agents_query_dirty_snapshot
            if dirty is None:
                return
            task = self._agents_query_save_task
            if task is not None and not task.done():
                return
            if self._agents_query_save_pending is not None:
                return
            _dirty_generation, snapshot = dirty
            if snapshot == self._agents_query_durable_snapshot:
                self._agents_query_dirty_snapshot = None
                return
            generation = self._agents_query_save_generation + 1
            self._agents_query_save_generation = generation
            self._agents_query_save_pending = (generation, snapshot)
            self._agents_query_queued_snapshot = snapshot
            self._start_agents_query_writer()
            await _await_generation(generation)

        try:
            await asyncio.wait_for(_flush(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("Timed out flushing Agents query state during controlled exit")
        except Exception:
            log.exception("Agents query flush failed during controlled exit")


__all__ = ["AgentQueryPersistenceMixin"]
