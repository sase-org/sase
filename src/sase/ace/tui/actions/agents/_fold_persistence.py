"""Non-blocking lifecycle for persisted Agents-tab fold state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from textual.worker import Worker

    from ...models.agent_fold_persistence import AgentsFoldStateSnapshot
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...models.group_fold import GroupKey

log = logging.getLogger(__name__)

_MAX_INTENT_JOURNAL_ENTRIES = 4352
_FLUSH_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class _AgentGroupFoldIntent:
    """One pre-load group-fold mutation that must win over disk state."""

    mode: GroupingMode
    panel_key: PanelKey
    merged: bool
    group_key: GroupKey
    collapsed: bool


@dataclass(frozen=True)
class _AgentPanelFoldIntent:
    """One pre-load whole-panel mutation."""

    panel_key: PanelKey
    collapsed: bool


@dataclass(frozen=True)
class _AgentPanelFoldsClearIntent:
    """A split-to-merged transition clearing every whole-panel fold."""


type AgentFoldIntent = (
    _AgentGroupFoldIntent | _AgentPanelFoldIntent | _AgentPanelFoldsClearIntent
)


class AgentFoldPersistenceMixin:
    """Load, merge, journal, save, and flush Agents-tab collapse intent."""

    _grouping_mode: GroupingMode
    _group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry]
    _group_fold_registry: AgentGroupFoldRegistry
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]
    _current_group_key: GroupKey | None
    _agents_first_load_done: bool

    _agents_fold_state_load_started: bool
    _agents_fold_state_load_resolved: bool
    _agents_fold_state_loaded_snapshot: AgentsFoldStateSnapshot | None
    _agents_fold_state_merged: bool
    _agents_fold_state_intents: list[AgentFoldIntent]
    _agents_fold_state_save_requested: bool
    _agents_fold_state_save_generation: int
    _agents_fold_state_completed_generation: int
    _agents_fold_state_save_pending: tuple[int, AgentsFoldStateSnapshot] | None
    _agents_fold_state_save_task: asyncio.Task[None] | None
    _agents_fold_state_load_worker: Worker[Any] | None
    _agents_fold_restore_needs_focus_snap: bool

    def _ensure_agents_fold_persistence_state(self) -> None:
        """Initialize fields for direct-mixin tests that bypass app startup."""
        from ...models.agent_fold_persistence import AgentsFoldStateSnapshot

        defaults: tuple[tuple[str, object], ...] = (
            ("_agents_fold_state_load_started", False),
            ("_agents_fold_state_load_resolved", False),
            ("_agents_fold_state_loaded_snapshot", None),
            ("_agents_fold_state_merged", False),
            ("_agents_fold_state_intents", []),
            ("_agents_fold_state_save_requested", False),
            ("_agents_fold_state_save_generation", 0),
            ("_agents_fold_state_completed_generation", 0),
            ("_agents_fold_state_save_pending", None),
            ("_agents_fold_state_save_task", None),
            ("_agents_fold_state_load_worker", None),
            ("_agents_fold_restore_needs_focus_snap", False),
        )
        for name, value in defaults:
            if not hasattr(self, name):
                setattr(self, name, value)
        loaded = self._agents_fold_state_loaded_snapshot
        if loaded is not None and not isinstance(loaded, AgentsFoldStateSnapshot):
            self._agents_fold_state_loaded_snapshot = None

    def _record_agents_group_fold_change(
        self,
        group_key: GroupKey,
        *,
        collapsed: bool,
    ) -> None:
        """Journal and schedule persistence for one successful group mutation."""
        from ...models.agent_group_fold import AgentPanelFoldScope
        from ...models.agent_groups import GroupingMode

        mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        panel_key = panel_group.focused_key if panel_group is not None else None
        scope = AgentPanelFoldScope(
            panel_key=panel_key,
            merged=bool(getattr(self, "_agent_panels_grouped", False)),
        )
        self._agents_fold_state_changed(
            _AgentGroupFoldIntent(
                mode=mode,
                panel_key=scope.panel_key,
                merged=scope.merged,
                group_key=tuple(group_key),
                collapsed=collapsed,
            )
        )

    def _record_agents_panel_fold_change(
        self,
        panel_key: PanelKey,
        *,
        collapsed: bool,
    ) -> None:
        """Journal and schedule persistence for a whole-panel mutation."""
        self._agents_fold_state_changed(
            _AgentPanelFoldIntent(panel_key=panel_key, collapsed=collapsed)
        )

    def _record_agents_panel_folds_cleared(self) -> None:
        """Journal a layout transition that semantically clears all panels."""
        self._agents_fold_state_changed(_AgentPanelFoldsClearIntent())

    def _agents_fold_state_changed(
        self,
        intent: AgentFoldIntent | None = None,
    ) -> None:
        """Record pre-load intent or enqueue the latest immutable snapshot."""
        self._ensure_agents_fold_persistence_state()
        if not self._agents_fold_state_merged:  # type: ignore[attr-defined]
            if intent is not None:
                journal: list[AgentFoldIntent] = self._agents_fold_state_intents  # type: ignore[attr-defined]
                journal.append(intent)
                if len(journal) > _MAX_INTENT_JOURNAL_ENTRIES:
                    del journal[: len(journal) - _MAX_INTENT_JOURNAL_ENTRIES]
                    log.warning("Agents fold intent journal reached its size limit")
            self._agents_fold_state_save_requested = True  # type: ignore[attr-defined]
            return
        self._schedule_agents_fold_state_save()

    def _capture_agents_fold_state(self) -> AgentsFoldStateSnapshot:
        """Capture all modes/scopes and whole-panel folds immutably."""
        from ...models.agent_fold_persistence import (
            AgentGroupingFoldSnapshot,
            AgentsFoldStateSnapshot,
        )
        from ...models.agent_group_fold import AgentGroupFoldRegistry

        group_folds: list[AgentGroupingFoldSnapshot] = []
        for mode, registry in getattr(self, "_group_fold_registries", {}).items():
            if not isinstance(registry, AgentGroupFoldRegistry):
                continue
            scopes = registry.snapshot()
            if scopes:
                group_folds.append(AgentGroupingFoldSnapshot(mode, scopes))
        return AgentsFoldStateSnapshot(
            collapsed_panels=frozenset(getattr(self, "_collapsed_panel_keys", set())),
            group_folds=tuple(group_folds),
        )

    def _replay_agents_fold_intent(self, intent: AgentFoldIntent) -> None:
        """Apply one journal entry after the disk baseline is installed."""
        from ...models.agent_group_fold import (
            AgentGroupFoldRegistry,
            AgentPanelFoldScope,
        )

        if isinstance(intent, _AgentPanelFoldsClearIntent):
            self._collapsed_panel_keys.clear()  # type: ignore[attr-defined]
            return
        if isinstance(intent, _AgentPanelFoldIntent):
            collapsed = self._collapsed_panel_keys  # type: ignore[attr-defined]
            if intent.collapsed:
                collapsed.add(intent.panel_key)
            else:
                collapsed.discard(intent.panel_key)
            return

        registries = self._group_fold_registries  # type: ignore[attr-defined]
        owner = registries.get(intent.mode)
        if owner is None:
            owner = AgentGroupFoldRegistry()
            registries[intent.mode] = owner
        scope = AgentPanelFoldScope(intent.panel_key, merged=intent.merged)
        registry = owner.for_panel(scope.panel_key, merged=scope.merged)
        if intent.collapsed:
            registry.collapse(intent.group_key)
        else:
            registry.expand(intent.group_key)

    def _install_loaded_agents_fold_state(self, *, refresh: bool) -> bool:
        """Install the baseline, replay user intent, and optionally refilter."""
        self._ensure_agents_fold_persistence_state()
        if (
            self._agents_fold_state_merged  # type: ignore[attr-defined]
            or not self._agents_fold_state_load_resolved  # type: ignore[attr-defined]
        ):
            return False

        from ...models.agent_fold_persistence import EMPTY_AGENTS_FOLD_STATE
        from ...models.agent_group_fold import AgentGroupFoldRegistry

        snapshot = (
            self._agents_fold_state_loaded_snapshot  # type: ignore[attr-defined]
            or EMPTY_AGENTS_FOLD_STATE
        )
        restored: dict[Any, AgentGroupFoldRegistry] = {}
        for mode_snapshot in snapshot.group_folds:
            owner = AgentGroupFoldRegistry()
            owner.restore(mode_snapshot.scopes)
            restored[mode_snapshot.mode] = owner

        active_mode = self._grouping_mode  # type: ignore[attr-defined]
        restored.setdefault(active_mode, AgentGroupFoldRegistry())
        self._group_fold_registries = restored  # type: ignore[attr-defined]
        self._group_fold_registry = restored[active_mode]  # type: ignore[attr-defined]
        self._collapsed_panel_keys = set(snapshot.collapsed_panels)  # type: ignore[attr-defined]

        journal: list[AgentFoldIntent] = list(
            self._agents_fold_state_intents  # type: ignore[attr-defined]
        )
        for intent in journal:
            self._replay_agents_fold_intent(intent)
        self._agents_fold_state_intents.clear()  # type: ignore[attr-defined]
        self._agents_fold_state_loaded_snapshot = None  # type: ignore[attr-defined]
        self._agents_fold_state_merged = True  # type: ignore[attr-defined]
        self._current_group_key = None  # type: ignore[attr-defined]
        self._agents_fold_restore_needs_focus_snap = True  # type: ignore[attr-defined]

        if self._agents_fold_state_save_requested:  # type: ignore[attr-defined]
            self._agents_fold_state_save_requested = False  # type: ignore[attr-defined]
            self._schedule_agents_fold_state_save()
        if refresh:
            refilter = getattr(self, "_refilter_agents", None)
            if callable(refilter):
                # An empty previous list deliberately selects the established
                # full-rebuild branch so changed fold structure cannot be
                # mistaken for an identity-only incremental patch.
                refilter(previous_agents=[])
        return True

    def _maybe_install_agents_fold_state_before_finalize(self) -> bool:
        """Fast-load hook used at the first real Agents finalize boundary."""
        return self._install_loaded_agents_fold_state(refresh=False)

    def _resolve_agents_fold_state_load(
        self, snapshot: AgentsFoldStateSnapshot
    ) -> None:
        self._ensure_agents_fold_persistence_state()
        self._agents_fold_state_loaded_snapshot = snapshot  # type: ignore[attr-defined]
        self._agents_fold_state_load_resolved = True  # type: ignore[attr-defined]
        if getattr(self, "_agents_first_load_done", False):
            self._install_loaded_agents_fold_state(refresh=True)

    async def _run_agents_fold_state_load(self) -> None:
        """Read/decode the one-shot baseline entirely off the event loop."""
        from ...models.agent_fold_persistence import (
            EMPTY_AGENTS_FOLD_STATE,
            load_agents_fold_state,
        )

        try:
            snapshot = await asyncio.to_thread(load_agents_fold_state)
        except Exception:
            log.exception("Agents fold state load failed")
            snapshot = EMPTY_AGENTS_FOLD_STATE
        self._resolve_agents_fold_state_load(snapshot)

    def _schedule_agents_fold_state_load(self) -> None:
        """Launch the post-first-paint load without gating other startup work."""
        self._ensure_agents_fold_persistence_state()
        if (
            self._agents_fold_state_load_started  # type: ignore[attr-defined]
            or self._agents_fold_state_load_resolved  # type: ignore[attr-defined]
        ):
            return
        self._agents_fold_state_load_started = True  # type: ignore[attr-defined]
        try:
            worker = self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_agents_fold_state_load),
                thread=False,
                exclusive=False,
                group="startup-fold-state",
            )
            self._agents_fold_state_load_worker = worker  # type: ignore[attr-defined]
        except Exception:
            log.exception("Failed to schedule Agents fold state load")
            from ...models.agent_fold_persistence import EMPTY_AGENTS_FOLD_STATE

            self._resolve_agents_fold_state_load(EMPTY_AGENTS_FOLD_STATE)

    def _save_agents_fold_state_now(self, snapshot: AgentsFoldStateSnapshot) -> None:
        from ...models.agent_fold_persistence import save_agents_fold_state

        save_agents_fold_state(snapshot)

    def _schedule_agents_fold_state_save(self) -> None:
        """Coalesce persistence to an immutable latest-generation snapshot."""
        self._ensure_agents_fold_persistence_state()
        if not self._agents_fold_state_merged:  # type: ignore[attr-defined]
            self._agents_fold_state_save_requested = True  # type: ignore[attr-defined]
            return
        generation = self._agents_fold_state_save_generation + 1  # type: ignore[attr-defined]
        self._agents_fold_state_save_generation = generation  # type: ignore[attr-defined]
        self._agents_fold_state_save_pending = (  # type: ignore[attr-defined]
            generation,
            self._capture_agents_fold_state(),
        )
        self._start_agents_fold_state_save_writer()

    def _start_agents_fold_state_save_writer(self) -> None:
        """Start the writer for an existing pending generation when possible."""
        task: asyncio.Task[None] | None = self._agents_fold_state_save_task  # type: ignore[attr-defined]
        if task is not None and not task.done():
            return
        if self._agents_fold_state_save_pending is None:  # type: ignore[attr-defined]
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._agents_fold_state_save_task = loop.create_task(  # type: ignore[attr-defined]
            self._run_agents_fold_state_save_loop()
        )

    async def _run_agents_fold_state_save_loop(self) -> None:
        """Run one writer at a time until the newest generation is durable."""
        try:
            while True:
                pending = self._agents_fold_state_save_pending  # type: ignore[attr-defined]
                self._agents_fold_state_save_pending = None  # type: ignore[attr-defined]
                if pending is None:
                    break
                generation, snapshot = pending
                try:
                    await asyncio.to_thread(
                        self._save_agents_fold_state_now,
                        snapshot,
                    )
                except Exception:
                    log.exception("Agents fold state save failed")
                finally:
                    self._agents_fold_state_completed_generation = max(  # type: ignore[attr-defined]
                        self._agents_fold_state_completed_generation,  # type: ignore[attr-defined]
                        generation,
                    )
        finally:
            self._agents_fold_state_save_task = None  # type: ignore[attr-defined]
            if self._agents_fold_state_save_pending is not None:  # type: ignore[attr-defined]
                self._start_agents_fold_state_save_writer()

    async def _flush_agents_fold_state(self) -> None:
        """Await the already-queued latest generation with a bounded timeout."""
        self._ensure_agents_fold_persistence_state()
        needs_merge = bool(
            self._agents_fold_state_save_requested  # type: ignore[attr-defined]
            and not self._agents_fold_state_merged  # type: ignore[attr-defined]
        )

        async def _flush() -> None:
            if needs_merge:
                worker: Worker[Any] | None = self._agents_fold_state_load_worker  # type: ignore[attr-defined]
                if worker is not None:
                    await worker.wait()
                elif not self._agents_fold_state_load_resolved:  # type: ignore[attr-defined]
                    from ...models.agent_fold_persistence import load_agents_fold_state

                    snapshot = await asyncio.to_thread(load_agents_fold_state)
                    self._resolve_agents_fold_state_load(snapshot)
                self._install_loaded_agents_fold_state(refresh=False)

            if (
                self._agents_fold_state_merged  # type: ignore[attr-defined]
                and self._agents_fold_state_save_requested  # type: ignore[attr-defined]
            ):
                self._agents_fold_state_save_requested = False  # type: ignore[attr-defined]
                self._schedule_agents_fold_state_save()

            target = self._agents_fold_state_save_generation  # type: ignore[attr-defined]
            while self._agents_fold_state_completed_generation < target:  # type: ignore[attr-defined]
                task: asyncio.Task[None] | None = self._agents_fold_state_save_task  # type: ignore[attr-defined]
                if task is None:
                    if self._agents_fold_state_save_pending is None:  # type: ignore[attr-defined]
                        break
                    self._start_agents_fold_state_save_writer()
                    await asyncio.sleep(0)
                    continue
                await asyncio.shield(task)

        try:
            await asyncio.wait_for(_flush(), timeout=_FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            log.warning("Timed out flushing Agents fold state during controlled exit")
        except Exception:
            log.exception("Agents fold state flush failed during controlled exit")


__all__ = [
    "AgentFoldPersistenceMixin",
]
