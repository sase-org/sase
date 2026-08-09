"""Grouping-mode cycle action shared by the Agents and Patches tabs.

The cycle key (``o`` by default) advances per-tab grouping state and
re-renders that tab.  Per-mode fold registries are kept in
:attr:`_group_fold_registries` (Agents) and
:attr:`_patch_group_fold_registries` (Patches) so a mode-specific
collapse layout is restored when the user cycles back to a
previously-visited mode.

On the AXE tab the action is a silent no-op; AXE has no grouping model.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Literal

from ...util.pump_tasks import spawn_pump_free_task

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.patch_groups import PatchGroupingMode
    from ...models.group_fold import GroupFoldRegistry

TabName = Literal["artifacts", "patches", "changespecs", "agents", "axe"]
GroupingSaveTarget = Literal["agents", "artifacts", "changespecs"]

log = logging.getLogger(__name__)

#: Agents-tab cycle order — STANDARD is included so a single press from
#: BY_STATUS lands the user back at the project default.
_GROUPING_CYCLE: tuple[str, ...] = ("STANDARD", "BY_DATE", "BY_STATUS")

#: Human-readable labels for the Agents-tab toast emitted on each step.
_MODE_LABELS: dict[str, str] = {
    "STANDARD": "by project",
    "BY_DATE": "by date",
    "BY_STATUS": "by status",
}

#: Patches-tab cycle order — BY_PROJECT is the first-paint default; the cycle
#: walks through the three real grouping strategies and wraps back.
_CHANGESPEC_GROUPING_CYCLE: tuple[str, ...] = (
    "BY_PROJECT",
    "BY_DATE",
    "BY_STATUS",
)

#: Human-readable labels for the Patches-tab toast emitted on each step.
_CHANGESPEC_MODE_LABELS: dict[str, str] = {
    "BY_PROJECT": "by project",
    "BY_DATE": "by date",
    "BY_STATUS": "by status",
}


class AgentGroupingMixin:
    """Mixin providing the ``cycle_grouping_mode`` action."""

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _grouping_mode: GroupingMode
    _group_fold_registry: AgentGroupFoldRegistry
    _group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry]
    _current_group_key: tuple[str, ...] | None
    _patch_grouping_mode: PatchGroupingMode
    _patch_group_fold_registry: GroupFoldRegistry
    _patch_group_fold_registries: dict[PatchGroupingMode, GroupFoldRegistry]
    _current_patch_group_key: tuple[str, ...] | None
    _grouping_mode_save_pending: dict[str, object]
    _grouping_mode_save_inflight: set[str]
    _grouping_mode_save_active: dict[str, object]

    @property
    def _changespec_grouping_mode(self) -> Any:
        return getattr(self, "_patch_grouping_mode", None)

    @_changespec_grouping_mode.setter
    def _changespec_grouping_mode(self, value: Any) -> None:
        self._patch_grouping_mode = value

    @property
    def _changespec_group_fold_registry(self) -> Any:
        return getattr(self, "_patch_group_fold_registry", None)

    @_changespec_group_fold_registry.setter
    def _changespec_group_fold_registry(self, value: Any) -> None:
        self._patch_group_fold_registry = value

    @property
    def _changespec_group_fold_registries(self) -> Any:
        return getattr(self, "_patch_group_fold_registries", {})

    @_changespec_group_fold_registries.setter
    def _changespec_group_fold_registries(self, value: Any) -> None:
        self._patch_group_fold_registries = value

    @property
    def _current_changespec_group_key(self) -> Any:
        return getattr(self, "_current_patch_group_key", None)

    @_current_changespec_group_key.setter
    def _current_changespec_group_key(self, value: Any) -> None:
        self._current_patch_group_key = value

    def _ensure_changespec_mode_registry(self, mode: Any) -> Any:
        return self._ensure_patch_mode_registry(mode)

    def _next_grouping_mode(self, *, reverse: bool = False) -> GroupingMode:
        """Return the mode that follows :attr:`_grouping_mode` in the cycle."""
        from ...models.agent_groups import GroupingMode

        order = [GroupingMode[name] for name in _GROUPING_CYCLE]
        try:
            idx = order.index(self._grouping_mode)
        except ValueError:
            return order[0]
        return order[(idx + (-1 if reverse else 1)) % len(order)]

    def _next_patch_grouping_mode(self, *, reverse: bool = False) -> PatchGroupingMode:
        """Return the PR mode that follows :attr:`_patch_grouping_mode`."""
        from ...models.patch_groups import PatchGroupingMode

        order = [PatchGroupingMode[name] for name in _CHANGESPEC_GROUPING_CYCLE]
        try:
            idx = order.index(self._patch_grouping_mode)
        except ValueError:
            return order[0]
        return order[(idx + (-1 if reverse else 1)) % len(order)]

    def _ensure_mode_registry(self, mode: GroupingMode) -> AgentGroupFoldRegistry:
        """Return the Agents fold registry for *mode*, lazily allocating one."""
        from ...models.agent_group_fold import AgentGroupFoldRegistry

        registry = self._group_fold_registries.get(mode)
        if registry is None:
            registry = AgentGroupFoldRegistry()
            self._group_fold_registries[mode] = registry
        return registry

    def _ensure_patch_mode_registry(self, mode: PatchGroupingMode) -> GroupFoldRegistry:
        """Return the PR fold registry for *mode*, lazily allocating one."""
        from ...models.group_fold import GroupFoldRegistry

        registry = self._patch_group_fold_registries.get(mode)
        if registry is None:
            registry = GroupFoldRegistry()
            self._patch_group_fold_registries[mode] = registry
        return registry

    def _ensure_grouping_mode_save_state(self) -> None:
        """Initialize save-coalescing attributes for direct mixin tests."""
        if not hasattr(self, "_grouping_mode_save_pending"):
            self._grouping_mode_save_pending = {}
        if not hasattr(self, "_grouping_mode_save_inflight"):
            self._grouping_mode_save_inflight = set()
        if not hasattr(self, "_grouping_mode_save_active"):
            self._grouping_mode_save_active = {}

    def _schedule_grouping_mode_save(
        self,
        target: GroupingSaveTarget,
        mode: GroupingMode | PatchGroupingMode,
    ) -> None:
        """Persist the latest grouping mode for *target* off the key path."""
        self._ensure_grouping_mode_save_state()
        self._grouping_mode_save_pending[target] = mode
        if target in self._grouping_mode_save_inflight:
            return
        self._start_grouping_mode_save(target)

    def _start_grouping_mode_save(self, target: GroupingSaveTarget) -> None:
        mode = self._grouping_mode_save_pending.get(target)
        if mode is None:
            return
        self._grouping_mode_save_inflight.add(target)
        self._grouping_mode_save_active[target] = mode

        async def _runner() -> None:
            active_mode = self._grouping_mode_save_active[target]
            try:
                await asyncio.to_thread(
                    self._save_grouping_mode_now, target, active_mode
                )
            except Exception:
                log.exception("Grouping mode save failed for %s", target)
            finally:
                self._grouping_mode_save_inflight.discard(target)
                self._grouping_mode_save_active.pop(target, None)
                if self._grouping_mode_save_pending.get(target) is not active_mode:
                    self._start_grouping_mode_save(target)

        self._spawn_grouping_mode_save_task(target, _runner)

    def _spawn_grouping_mode_save_task(
        self,
        target: GroupingSaveTarget,
        coro_factory: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Spawn one latest-value persistence worker outside the app pump."""
        task = spawn_pump_free_task(
            self,
            coro_factory(),
            name=f"sase-grouping-mode-save-{target}",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._grouping_mode_save_inflight.discard(target)
            self._grouping_mode_save_active.pop(target, None)

    def _save_grouping_mode_now(
        self,
        target: GroupingSaveTarget,
        mode: object,
    ) -> bool:
        from ....grouping_strategy import (
            save_agent_grouping_mode,
            save_changespec_grouping_mode,
            save_patch_grouping_mode,
        )
        from ...models.agent_groups import GroupingMode
        from ...models.patch_groups import PatchGroupingMode

        if target == "agents":
            if not isinstance(mode, GroupingMode):
                return False
            return save_agent_grouping_mode(mode)
        if not isinstance(mode, PatchGroupingMode):
            return False
        if target == "changespecs":
            return save_changespec_grouping_mode(mode)
        return save_patch_grouping_mode(mode)

    def action_cycle_grouping_mode(self) -> None:
        """Advance the focused tab's grouping mode by one step.

        On Agents and Patches the active mode advances and the tab is
        refreshed.  On AXE (which has no grouping model) the action is a
        silent no-op.
        """
        if self.current_tab == "agents":
            self._cycle_agents_grouping_mode()
        elif self.current_tab in {"artifacts", "patches", "changespecs"}:
            self._cycle_patch_grouping_mode()

    def action_cycle_grouping_mode_reverse(self) -> None:
        """Advance the focused tab's grouping mode by one step in reverse."""
        if self.current_tab == "agents":
            self._cycle_agents_grouping_mode(reverse=True)
        elif self.current_tab in {"artifacts", "patches", "changespecs"}:
            self._cycle_patch_grouping_mode(reverse=True)

    def _cycle_agents_grouping_mode(self, *, reverse: bool = False) -> None:
        next_mode = self._next_grouping_mode(reverse=reverse)
        if next_mode is self._grouping_mode:
            return
        self._grouping_mode = next_mode
        # Swap the active fold registry so existing call sites (loading,
        # folding, display) continue to read ``_group_fold_registry``.
        self._group_fold_registry = self._ensure_mode_registry(next_mode)
        # Banner focus from the previous mode keys a different tree;
        # snap back to agent focus so the renderer doesn't try to
        # highlight a missing banner.
        self._current_group_key = None
        self._schedule_grouping_mode_save("agents", next_mode)
        try:
            label = _MODE_LABELS.get(next_mode.name, next_mode.name)
            self.notify(  # type: ignore[attr-defined]
                f"Grouping: {label}", timeout=1.5
            )
        except Exception:
            pass
        self._refilter_agents()  # type: ignore[attr-defined]

    def _cycle_patch_grouping_mode(self, *, reverse: bool = False) -> None:
        next_mode = self._next_patch_grouping_mode(reverse=reverse)
        if next_mode is self._patch_grouping_mode:
            return
        self._patch_grouping_mode = next_mode
        self._patch_group_fold_registry = self._ensure_patch_mode_registry(next_mode)
        # Drop any banner focus from the previous mode — its tuple key
        # belongs to a different tree and would highlight nothing.
        self._current_patch_group_key = None
        target: GroupingSaveTarget = (
            "artifacts" if self.current_tab == "artifacts" else "changespecs"
        )
        self._schedule_grouping_mode_save(target, next_mode)
        try:
            label = _CHANGESPEC_MODE_LABELS.get(next_mode.name, next_mode.name)
            self.notify(  # type: ignore[attr-defined]
                f"PR grouping: {label}", timeout=1.5
            )
        except Exception:
            pass
        self._refresh_display()  # type: ignore[attr-defined]
