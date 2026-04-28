"""Grouping-mode cycle action shared by the Agents and CLs tabs.

The cycle key (``o`` by default) advances per-tab grouping state and
re-renders that tab.  Per-mode fold registries are kept in
:attr:`_group_fold_registries` (Agents) and
:attr:`_changespec_group_fold_registries` (CLs) so a mode-specific
collapse layout is restored when the user cycles back to a
previously-visited mode.

On the AXE tab the action is a silent no-op; AXE has no grouping model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.changespec_groups import ChangeSpecGroupingMode
    from ...models.group_fold import GroupFoldRegistry

TabName = Literal["changespecs", "agents", "axe"]

#: Agents-tab cycle order — STANDARD is included so a single press from
#: BY_STATUS lands the user back at the project default.
_GROUPING_CYCLE: tuple[str, ...] = ("STANDARD", "BY_DATE", "BY_STATUS")

#: Human-readable labels for the Agents-tab toast emitted on each step.
_MODE_LABELS: dict[str, str] = {
    "STANDARD": "by project",
    "BY_DATE": "by date",
    "BY_STATUS": "by status",
}

#: CLs-tab cycle order — BY_PROJECT is the first-paint default; the cycle
#: walks through the three real grouping strategies and wraps back.
_CHANGESPEC_GROUPING_CYCLE: tuple[str, ...] = (
    "BY_PROJECT",
    "BY_DATE",
    "BY_STATUS",
)

#: Human-readable labels for the CLs-tab toast emitted on each step.
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
    _changespec_grouping_mode: ChangeSpecGroupingMode
    _changespec_group_fold_registry: GroupFoldRegistry
    _changespec_group_fold_registries: dict[ChangeSpecGroupingMode, GroupFoldRegistry]
    _current_changespec_group_key: tuple[str, ...] | None

    def _next_grouping_mode(self) -> GroupingMode:
        """Return the mode that follows :attr:`_grouping_mode` in the cycle."""
        from ...models.agent_groups import GroupingMode

        order = [GroupingMode[name] for name in _GROUPING_CYCLE]
        try:
            idx = order.index(self._grouping_mode)
        except ValueError:
            return order[0]
        return order[(idx + 1) % len(order)]

    def _next_changespec_grouping_mode(self) -> ChangeSpecGroupingMode:
        """Return the CL mode that follows :attr:`_changespec_grouping_mode`."""
        from ...models.changespec_groups import ChangeSpecGroupingMode

        order = [ChangeSpecGroupingMode[name] for name in _CHANGESPEC_GROUPING_CYCLE]
        try:
            idx = order.index(self._changespec_grouping_mode)
        except ValueError:
            return order[0]
        return order[(idx + 1) % len(order)]

    def _ensure_mode_registry(self, mode: GroupingMode) -> AgentGroupFoldRegistry:
        """Return the Agents fold registry for *mode*, lazily allocating one."""
        from ...models.agent_group_fold import AgentGroupFoldRegistry

        registry = self._group_fold_registries.get(mode)
        if registry is None:
            registry = AgentGroupFoldRegistry()
            self._group_fold_registries[mode] = registry
        return registry

    def _ensure_changespec_mode_registry(
        self, mode: ChangeSpecGroupingMode
    ) -> GroupFoldRegistry:
        """Return the CL fold registry for *mode*, lazily allocating one."""
        from ...models.group_fold import GroupFoldRegistry

        registry = self._changespec_group_fold_registries.get(mode)
        if registry is None:
            registry = GroupFoldRegistry()
            self._changespec_group_fold_registries[mode] = registry
        return registry

    def action_cycle_grouping_mode(self) -> None:
        """Advance the focused tab's grouping mode by one step.

        On Agents and CLs the active mode advances and the tab is
        refreshed.  On AXE (which has no grouping model) the action is a
        silent no-op.
        """
        if self.current_tab == "agents":
            self._cycle_agents_grouping_mode()
        elif self.current_tab == "changespecs":
            self._cycle_changespec_grouping_mode()

    def _cycle_agents_grouping_mode(self) -> None:
        from ....grouping_mode_state import save_grouping_mode

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

    def _cycle_changespec_grouping_mode(self) -> None:
        from ....changespec_grouping_mode_state import save_changespec_grouping_mode

        next_mode = self._next_changespec_grouping_mode()
        if next_mode is self._changespec_grouping_mode:
            return
        self._changespec_grouping_mode = next_mode
        save_changespec_grouping_mode(next_mode)
        self._changespec_group_fold_registry = self._ensure_changespec_mode_registry(
            next_mode
        )
        # Drop any banner focus from the previous mode — its tuple key
        # belongs to a different tree and would highlight nothing.
        self._current_changespec_group_key = None
        try:
            label = _CHANGESPEC_MODE_LABELS.get(next_mode.name, next_mode.name)
            self.notify(  # type: ignore[attr-defined]
                f"CL grouping: {label}", timeout=1.5
            )
        except Exception:
            pass
        self._refresh_display()  # type: ignore[attr-defined]
