"""Agent fold state management methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldState
    from ...models.fold_state import FoldStateManager

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentFoldingMixin:
    """Mixin providing agent fold state management methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]
    _group_fold_state: AgentGroupFoldState
    _current_group_key: tuple[str, ...] | None

    def _get_workflow_key_for_agent(self, agent: Agent) -> str | None:
        """Get the fold state key for an agent (workflow parent or child).

        Args:
            agent: The agent to get the key for.

        Returns:
            The workflow raw_suffix key, or None if not a foldable agent.
        """
        from ...models.agent import AgentType

        if agent.is_workflow_child and agent.parent_timestamp:
            return agent.parent_timestamp
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and agent.raw_suffix
        ):
            return agent.raw_suffix
        return None

    def _get_all_workflow_keys(self) -> list[str]:
        """Get all foldable workflow keys from current fold counts.

        Returns:
            List of workflow raw_suffix strings.
        """
        return list(self._fold_counts.keys())

    def _snap_focus_after_group_fold_change(self) -> None:
        """Reposition ``current_idx`` / ``_current_group_key`` after a fold change.

        At fold level < 3 agents are hidden — focus snaps to the nearest
        visible ancestor banner of the previously selected agent so the
        user never loses their place.  At fold level == 3 banners are
        non-selectable, so any pending banner focus is cleared and
        focus stays on the underlying agent.
        """
        from ...models.agent_groups import (
            build_agent_tree,
            find_visible_ancestor_banner,
        )

        level = self._group_fold_state.level
        if level >= 3:
            self._current_group_key = None
            return
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return
        entries = build_agent_tree(self._agents, group_fold_level=level)
        ancestor = find_visible_ancestor_banner(entries, self.current_idx)
        if ancestor is not None:
            self._current_group_key = ancestor.group_key

    def _expand_fold(self) -> None:
        """Expand the fold for the selected workflow (one level).

        At group fold level < 3, ``l`` instead steps the global group
        fold so the user reaches the agent rows before per-workflow fold
        logic kicks in.  Once at level 3 the original Phase 3 behavior
        (single-workflow expansion) returns.
        """
        if self.current_tab == "agents" and self._group_fold_state.level < 3:
            if self._group_fold_state.expand():
                self._snap_focus_after_group_fold_change()
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        key = self._get_workflow_key_for_agent(agent)
        if key is None:
            return

        if self._fold_manager.expand(key):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _collapse_fold(self) -> None:
        """Collapse the fold for the selected workflow (one level).

        ``h`` first tries to collapse the per-workflow fold for the
        focused agent (Phase 3 behavior).  When the selected workflow is
        already at ``COLLAPSED`` (or no workflow is focused), the global
        group fold steps down a level instead, so the user can climb
        back up the L3 → L2 → L1 → L0 ladder.
        """
        if self.current_tab == "agents":
            from ...models.fold_state import FoldLevel

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None:
                key = self._get_workflow_key_for_agent(agent)
                if (
                    key is not None
                    and self._fold_manager.get(key) != FoldLevel.COLLAPSED
                ):
                    if agent.is_workflow_child and agent.parent_timestamp:
                        if self._fold_manager.get(key) == FoldLevel.EXPANDED:
                            for idx, a in enumerate(self._agents):
                                if (
                                    a.raw_suffix == agent.parent_timestamp
                                    and not a.is_workflow_child
                                ):
                                    self.current_idx = idx
                                    break
                    if self._fold_manager.collapse(key):
                        self._refilter_agents()  # type: ignore[attr-defined]
                    return

            # Fall through to group-level collapse.
            if self._group_fold_state.collapse():
                self._snap_focus_after_group_fold_change()
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        # Non-agents tabs: preserve original per-workflow behavior.
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        key = self._get_workflow_key_for_agent(agent)
        if key is None:
            return
        from ...models.fold_state import FoldLevel

        if agent.is_workflow_child and agent.parent_timestamp:
            if self._fold_manager.get(key) == FoldLevel.EXPANDED:
                for idx, a in enumerate(self._agents):
                    if (
                        a.raw_suffix == agent.parent_timestamp
                        and not a.is_workflow_child
                    ):
                        self.current_idx = idx
                        break

        if self._fold_manager.collapse(key):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _get_focused_panel_workflow_keys(self) -> list[str]:
        """Get workflow keys for agents in the currently focused panel.

        Returns:
            List of unique workflow raw_suffix strings from the focused panel.
        """
        indices = self._active_panel_indices()  # type: ignore[attr-defined]
        seen: set[str] = set()
        keys: list[str] = []
        for i in indices:
            agent = self._agents[i]
            key = self._get_workflow_key_for_agent(agent)
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _expand_all_folds(self) -> None:
        """Jump to the fully-expanded endpoint (``L`` action).

        On the agents tab this means: snap the global group fold to L3
        (so all banners + agents are visible) and then advance every
        per-workflow fold to ``FULLY_EXPANDED``.  A single ``L`` press
        from any state lands the user at "everything visible".
        """
        if self.current_tab == "agents":
            changed = self._group_fold_state.expand_all()
            if changed:
                self._current_group_key = None
            keys = self._get_focused_panel_workflow_keys()
            # Step every workflow fold up to FULLY_EXPANDED.
            for key in keys:
                while self._fold_manager.expand(key):
                    changed = True
            if changed:
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        keys = self._get_focused_panel_workflow_keys()
        if not keys:
            return

        if self._fold_manager.expand_all(keys):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _collapse_all_folds(self) -> None:
        """Jump to the fully-collapsed endpoint (``H`` action).

        On the agents tab this means: collapse every per-workflow fold
        to ``COLLAPSED`` and then snap the global group fold to L0 (only
        tag banners visible).  A single ``H`` press always lands the
        user at "maximally collapsed".
        """
        if self.current_tab == "agents":
            keys = self._get_focused_panel_workflow_keys()
            changed = False
            for key in keys:
                while self._fold_manager.collapse(key):
                    changed = True
            if self._group_fold_state.collapse_all():
                self._snap_focus_after_group_fold_change()
                changed = True
            if changed:
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        keys = self._get_focused_panel_workflow_keys()
        if not keys:
            return

        if self._fold_manager.collapse_all(keys):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _expand_axe_fold(self) -> None:
        """Expand the AXE lumberjack fold."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        if axe_fold_manager.expand("axe"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_axe_fold(self) -> None:
        """Collapse the AXE lumberjack fold.

        If on a lumberjack child, navigate to parent first.
        """
        from ...widgets.bgcmd_list import LumberjackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            if isinstance(axe_items[self.current_idx], LumberjackItem):
                self.current_idx = 0  # Navigate to axe parent

        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        if axe_fold_manager.collapse("axe"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def action_expand_or_layout(self) -> None:
        """Expand fold on agents/axe tab, or no-op on other tabs."""
        if self.current_tab == "agents":
            self._expand_fold()
        elif self.current_tab == "axe":
            self._expand_axe_fold()

    def action_hooks_or_collapse(self) -> None:
        """Collapse fold on agents/axe tab, or edit hooks on CLs tab."""
        if self.current_tab == "agents":
            self._collapse_fold()
        elif self.current_tab == "axe":
            self._collapse_axe_fold()
        elif self.current_tab == "changespecs":
            self.action_edit_hooks()  # type: ignore[attr-defined]

    def action_hooks_or_collapse_all(self) -> None:
        """Collapse all folds on agents/axe tab, or hooks from failed on CLs tab."""
        if self.current_tab == "agents":
            self._collapse_all_folds()
        elif self.current_tab == "axe":
            self._collapse_axe_fold()
        elif self.current_tab == "changespecs":
            self.action_hooks_from_failed()  # type: ignore[attr-defined]

    def action_expand_all_folds(self) -> None:
        """Expand all workflow folds (agents/axe tab) or show agent run log (CLs tab)."""
        if self.current_tab == "agents":
            self._expand_all_folds()
        elif self.current_tab == "axe":
            self._expand_axe_fold()
        elif self.current_tab == "changespecs":
            self._show_agent_run_log()

    def _show_agent_run_log(self) -> None:
        """Open the Agent Run Log modal for the current CL."""
        from ...modals.agent_run_log_modal import AgentRunLogModal

        changespecs = self.changespecs  # type: ignore[attr-defined]
        if not changespecs:
            return
        changespec = changespecs[self.current_idx]
        self.app.push_screen(AgentRunLogModal(cl_name=changespec.name))  # type: ignore[attr-defined]
