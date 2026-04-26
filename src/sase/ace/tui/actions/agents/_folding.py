"""Agent fold state management methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
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
    _group_fold_registry: AgentGroupFoldRegistry
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

    def _focused_group_keys(self) -> tuple[GroupKey | None, GroupKey | None]:
        """Return ``(l1_key | None, l0_key | None)`` for the focused agent.

        Uses :func:`grouping_keys_for_agents` to map ``current_idx`` back
        to its enclosing project / name-root pair, mirroring the same
        singleton-suppression rule as :func:`build_agent_tree` so an L1
        key is only returned when the name-root group has 2+ entries.
        Returns ``(None, None)`` when no agent is focused.
        """
        from ...models.agent_groups import grouping_keys_for_agents

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return (None, None)
        keys_per_agent = grouping_keys_for_agents(self._agents)
        focus = keys_per_agent[self.current_idx]
        l0: GroupKey = focus.project
        l1: GroupKey | None = None
        if focus.name_root:
            sibling_count = sum(
                1
                for k in keys_per_agent
                if k.project == focus.project and k.name_root == focus.name_root
            )
            if sibling_count >= 2:
                l1 = (*focus.project, focus.name_root)
        return (l1, l0)

    def _all_known_group_keys(self) -> list[GroupKey]:
        """Every L0 + L1 key the current agent list would render."""
        from ...models.agent_groups import enumerate_group_keys

        return enumerate_group_keys(self._agents)

    def _snap_focus_after_group_fold_change(self) -> None:
        """Reposition ``current_idx`` / ``_current_group_key`` after a fold change.

        After a per-group fold mutation the previously focused agent
        may no longer be visible.  When the enclosing group(s) are
        still expanded and the focused agent stays visible, clear the
        banner key so focus is on the agent.  Otherwise snap to the
        deepest collapsed ancestor banner via
        :func:`find_visible_ancestor_banner`.
        """
        from ...models.agent_groups import (
            build_agent_tree,
            find_visible_ancestor_banner,
        )

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self._current_group_key = None
            return
        entries = build_agent_tree(
            self._agents, fold_registry=self._group_fold_registry
        )
        # If the focused agent's row is in the tree, focus stays on it.
        for entry in entries:
            if entry.kind == "agent" and entry.agent_idx == self.current_idx:
                self._current_group_key = None
                return
        ancestor = find_visible_ancestor_banner(entries, self.current_idx)
        if ancestor is not None:
            self._current_group_key = ancestor.group_key

    def _expand_fold(self) -> None:
        """Expand the fold for the focused row (one level).

        Per-group rules:

        * Banner focus → expand that group.
        * Agent focus → run the existing per-workflow expansion (the
          agent must already be inside an expanded group, since
          collapsed groups hide agents).
        * Other tabs preserve the original per-workflow behavior.
        """
        if self.current_tab == "agents":
            if self._current_group_key is not None:
                group_key: GroupKey = tuple(self._current_group_key)
                if self._group_fold_registry.expand(group_key):
                    # Re-anchor focus on the first visible agent of the
                    # expanded group (or the first remaining collapsed
                    # child banner) so the cursor doesn't sit on a row
                    # that is now disabled.
                    self._reanchor_after_banner_expansion(group_key)
                    self._refilter_agents()  # type: ignore[attr-defined]
                return

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                return
            wf_key = self._get_workflow_key_for_agent(agent)
            if wf_key is not None and self._fold_manager.expand(wf_key):
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        wf_key = self._get_workflow_key_for_agent(agent)
        if wf_key is None:
            return

        if self._fold_manager.expand(wf_key):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _reanchor_after_banner_expansion(self, expanded_key: GroupKey) -> None:
        """Move focus off a banner that just stopped being selectable.

        Picks (in order): the first remaining collapsed child banner of
        the expanded group, then the first visible agent of the group,
        then leaves selection alone.
        """
        from ...models.agent_groups import build_agent_tree

        entries = build_agent_tree(
            self._agents, fold_registry=self._group_fold_registry
        )
        # Find first collapsed child banner under the expanded group.
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            g = entry.group
            if (
                len(g.group_key) > len(expanded_key)
                and g.group_key[: len(expanded_key)] == expanded_key
                and g.is_collapsed
            ):
                self._current_group_key = g.group_key
                return
        # Fall back to the first visible agent inside the group.
        for entry in entries:
            if entry.kind == "agent" and entry.agent_idx is not None:
                if 0 <= entry.agent_idx < len(self._agents):
                    a = self._agents[entry.agent_idx]
                    from ...models.agent_groups import grouping_keys_for_agents

                    keys_per_agent = grouping_keys_for_agents(self._agents)
                    k = keys_per_agent[entry.agent_idx]
                    proj_key: GroupKey = k.project
                    if expanded_key == proj_key or (
                        len(expanded_key) == 3
                        and proj_key == expanded_key[:2]
                        and k.name_root == expanded_key[2]
                    ):
                        self._current_group_key = None
                        self.current_idx = entry.agent_idx
                        _ = a  # keep linter happy
                        return
        # Nothing better — clear group focus so j/k can rebind cleanly.
        self._current_group_key = None

    def _collapse_fold(self) -> None:
        """Collapse the fold for the focused row (one level).

        Per-group rules:

        * Per-workflow fold first (preserves today's "h collapses my
          workflow" behaviour for an agent inside an expanded group).
        * Banner focus → collapse that banner; if it's already collapsed
          and the banner is an L1, walk up and collapse the parent L0.
        * Agent focus with no per-workflow fold to step → collapse the
          enclosing group (L1 if present, else L0) and snap focus to
          its now-visible banner.
        """
        if self.current_tab == "agents":
            from ...models.fold_state import FoldLevel

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None and self._current_group_key is None:
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

            # Banner focus → collapse it (or escalate to parent L0).
            if self._current_group_key is not None:
                cur_key: GroupKey = tuple(self._current_group_key)
                if len(cur_key) == 3 and self._group_fold_registry.is_collapsed(
                    cur_key
                ):
                    parent_key: GroupKey = cur_key[:2]
                    if self._group_fold_registry.collapse(parent_key):
                        self._current_group_key = parent_key
                        self._refilter_agents()  # type: ignore[attr-defined]
                    return
                if self._group_fold_registry.collapse(cur_key):
                    self._refilter_agents()  # type: ignore[attr-defined]
                return

            # Agent focus, no per-workflow step left → collapse the
            # enclosing group and snap to its banner.
            l1_key, l0_key = self._focused_group_keys()
            target = l1_key or l0_key
            if target is not None and self._group_fold_registry.collapse(target):
                self._current_group_key = target
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
        """Get workflow keys for agents currently visible.

        Returns:
            List of unique workflow raw_suffix strings.
        """
        seen: set[str] = set()
        keys: list[str] = []
        for agent in self._agents:
            key = self._get_workflow_key_for_agent(agent)
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _expand_all_folds(self) -> None:
        """Jump to the fully-expanded endpoint (``L`` action).

        On the agents tab: expand every known L0/L1 group and advance
        every per-workflow fold to ``FULLY_EXPANDED``.  A single ``L``
        press from any state lands the user at "everything visible".
        """
        if self.current_tab == "agents":
            changed = self._group_fold_registry.expand_keys(
                self._all_known_group_keys()
            )
            if changed:
                self._current_group_key = None
            keys = self._get_focused_panel_workflow_keys()
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

        On the agents tab: collapse every per-workflow fold then mark
        every known L0/L1 group collapsed so only project banners
        remain visible.  A single ``H`` press always lands the user at
        "maximally collapsed".
        """
        if self.current_tab == "agents":
            keys = self._get_focused_panel_workflow_keys()
            changed = False
            for key in keys:
                while self._fold_manager.collapse(key):
                    changed = True
            if self._group_fold_registry.collapse_keys(self._all_known_group_keys()):
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
