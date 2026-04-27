"""Grouping-mode cycle action for the Agents tab.

The cycle key (``o`` by default) advances ``self._grouping_mode`` through
``STANDARD → BY_DATE → BY_STATUS → STANDARD`` and re-renders the agents
tab.  Per-mode fold registries are kept in :attr:`_group_fold_registries`
so a mode-specific collapse layout is restored when the user cycles back
to a previously-visited mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode

TabName = Literal["changespecs", "agents", "axe"]

#: Cycle order — STANDARD is included so a single press from
#: BY_STATUS lands the user back at the project/ChangeSpec default.
_GROUPING_CYCLE: tuple[str, ...] = ("STANDARD", "BY_DATE", "BY_STATUS")

#: Human-readable labels for the toast emitted on each cycle step.
_MODE_LABELS: dict[str, str] = {
    "STANDARD": "default",
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

    def _next_grouping_mode(self) -> GroupingMode:
        """Return the mode that follows :attr:`_grouping_mode` in the cycle."""
        from ...models.agent_groups import GroupingMode

        order = [GroupingMode[name] for name in _GROUPING_CYCLE]
        try:
            idx = order.index(self._grouping_mode)
        except ValueError:
            return order[0]
        return order[(idx + 1) % len(order)]

    def _ensure_mode_registry(self, mode: GroupingMode) -> AgentGroupFoldRegistry:
        """Return the fold registry for *mode*, lazily allocating one."""
        from ...models.agent_group_fold import AgentGroupFoldRegistry

        registry = self._group_fold_registries.get(mode)
        if registry is None:
            registry = AgentGroupFoldRegistry()
            self._group_fold_registries[mode] = registry
        return registry

    def action_cycle_grouping_mode(self) -> None:
        """Advance the agents-tab grouping mode by one step."""
        from ....grouping_mode_state import save_grouping_mode

        if self.current_tab != "agents":
            return

        next_mode = self._next_grouping_mode()
        if next_mode is self._grouping_mode:
            return
        self._grouping_mode = next_mode
        save_grouping_mode(next_mode)
        # Swap the active fold registry so existing call sites (loading,
        # folding, display) continue to read ``_group_fold_registry``.
        self._group_fold_registry = self._ensure_mode_registry(next_mode)
        # Banner focus from the previous mode keys a different tree;
        # snap back to agent focus so the renderer doesn't try to
        # highlight a missing banner.
        self._current_group_key = None
        try:
            label = _MODE_LABELS.get(next_mode.name, next_mode.name)
            self.notify(  # type: ignore[attr-defined]
                f"Grouping: {label}", timeout=1.5
            )
        except Exception:
            pass
        self._refilter_agents()  # type: ignore[attr-defined]
