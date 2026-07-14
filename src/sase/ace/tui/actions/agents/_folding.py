"""Agent fold state management methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._fold_scope import focused_panel_fold_registry, panel_fold_registry
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.fold_state import FoldStateManager
    from ...models.group_fold import GroupFoldRegistry

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
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None

    def _get_workflow_key_for_agent(self, agent: Agent) -> str | None:
        """Get the fold state key for an agent (workflow parent or child).

        Args:
            agent: The agent to get the key for.

        Returns:
            The workflow raw_suffix key, or None if not a foldable agent.
        """
        if agent.is_child_row and agent.parent_timestamp:
            return agent.parent_timestamp
        if not agent.is_child_row and agent.raw_suffix in self._fold_counts:
            return agent.raw_suffix
        return None

    def _get_all_workflow_keys(self) -> list[str]:
        """Get all foldable workflow keys from current fold counts.

        Returns:
            List of workflow raw_suffix strings.
        """
        return list(self._fold_counts.keys())

    def _active_grouping_mode(self) -> GroupingMode:
        """Return the active grouping mode, defaulting to STANDARD.

        Most call sites read ``self._grouping_mode`` directly; this
        helper exists so legacy tests that exercise the folding mixin
        without going through ``StartupMixin._init_app_state`` (and so
        never set the attribute) still get sensible behavior.
        """
        from ...models.agent_groups import GroupingMode

        return getattr(self, "_grouping_mode", GroupingMode.STANDARD)

    def _focused_panel_fold_context(
        self,
    ) -> tuple[list[int], list[Agent], GroupFoldRegistry]:
        """Return global indices, agents, and registry for the focused panel."""
        panel_group = getattr(self, "_panel_group", None)
        panel_key = panel_group.focused_key if panel_group is not None else None
        global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        return global_indices, panel_agents, panel_fold_registry(self, panel_key)

    def _rendered_panel_fold_contexts(
        self,
    ) -> list[tuple[list[int], list[Agent], GroupFoldRegistry]]:
        """Return render-order panel slices paired with their fold registries."""
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = panel_group.panel_keys if panel_group is not None else [None]
        return [
            (*rendered_panel_slice(self, key), panel_fold_registry(self, key))
            for key in panel_keys
        ]

    def _focused_group_keys(self) -> tuple[GroupKey | None, GroupKey | None]:
        """Return ``(deep_key | None, l0_key | None)`` for the focused agent.

        Uses :func:`grouping_keys_for_agents` plus
        :func:`build_agent_tree` to mirror the same per-panel mode +
        singleton-suppression rules the renderer applies.  ``deep_key``
        is the deepest banner that contains the focused agent (a name-
        root banner if visible, otherwise a ChangeSpec banner in 3-level
        mode), and ``l0_key`` is its project banner.  Returns
        ``(None, None)`` when no agent is focused.
        """
        from ...models.agent_groups import (
            build_agent_tree,
            find_visible_ancestor_banner,
        )

        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return (None, None)
        global_indices, panel_agents, _registry = self._focused_panel_fold_context()
        try:
            focused_local_idx = global_indices.index(self.current_idx)
        except ValueError:
            return (None, None)
        # Build with an empty registry so collapsed banners don't
        # short-circuit the search — we want every enclosing banner
        # the renderer would emit at full expansion.
        from ...models.group_fold import GroupFoldRegistry

        entries = build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=self._active_grouping_mode(),
        )
        l0: GroupKey | None = None
        deep: GroupKey | None = None
        for entry in entries:
            if entry.kind != "group" or entry.group is None:
                continue
            if focused_local_idx not in entry.group.agent_indices:
                continue
            if entry.group.level == 0:
                l0 = entry.group.group_key
            if deep is None or entry.group.level > 0:
                deep = entry.group.group_key
        if deep == l0:
            deep = None
        if l0 is None:
            ancestor = find_visible_ancestor_banner(entries, focused_local_idx)
            if ancestor is not None:
                l0 = ancestor.group_key
        return (deep, l0)

    def _all_known_group_keys(self) -> list[GroupKey]:
        """Every L0 + L1 key the current agent list would render."""
        from ...models.agent_groups import enumerate_group_keys

        return enumerate_group_keys(self._agents, mode=self._active_grouping_mode())

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
        global_indices, panel_agents, registry = self._focused_panel_fold_context()
        try:
            focused_local_idx = global_indices.index(self.current_idx)
        except ValueError:
            self._current_group_key = None
            return
        entries = build_agent_tree(
            panel_agents,
            fold_registry=registry,
            mode=self._active_grouping_mode(),
        )
        # If the focused agent's row is in the tree, focus stays on it.
        for entry in entries:
            if entry.kind == "agent" and entry.agent_idx == focused_local_idx:
                self._current_group_key = None
                return
        ancestor = find_visible_ancestor_banner(entries, focused_local_idx)
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
                registry = focused_panel_fold_registry(self)
                if registry.expand(group_key):
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

        global_indices, panel_agents, registry = self._focused_panel_fold_context()
        entries = build_agent_tree(
            panel_agents,
            fold_registry=registry,
            mode=self._active_grouping_mode(),
        )
        # Find the agent_indices the expanded banner covers, so we can
        # match either by descendant-banner key prefix or by agent
        # membership without re-deriving the panel mode here.
        expanded_member_indices: tuple[int, ...] = ()
        for entry in entries:
            if entry.kind == "group" and entry.group is not None:
                if entry.group.group_key == expanded_key:
                    expanded_member_indices = entry.group.agent_indices
                    break
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
                if entry.agent_idx in expanded_member_indices:
                    self._current_group_key = None
                    if 0 <= entry.agent_idx < len(global_indices):
                        self.current_idx = global_indices[entry.agent_idx]
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

            # Banner focus → collapse it (or escalate to parent banner).
            if self._current_group_key is not None:
                cur_key: GroupKey = tuple(self._current_group_key)
                registry = focused_panel_fold_registry(self)
                if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                    parent_key: GroupKey = cur_key[:-1]
                    if registry.collapse(parent_key):
                        self._current_group_key = parent_key
                        self._refilter_agents()  # type: ignore[attr-defined]
                    return
                if registry.collapse(cur_key):
                    self._refilter_agents()  # type: ignore[attr-defined]
                return

            # Agent focus, no per-workflow step left → collapse the
            # enclosing group and snap to its banner.
            l1_key, l0_key = self._focused_group_keys()
            target = l1_key or l0_key
            registry = focused_panel_fold_registry(self)
            if target is not None and registry.collapse(target):
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
        """Advance the visible tree by one level (``L`` action).

        On the agents tab: walk the snapshot of currently-visible
        entries and apply a single-level expand to each — collapsed
        banners become expanded, and visible workflow folds step one
        notch toward ``FULLY_EXPANDED``.  Rows that become visible *as
        a result of* this press are not stepped; the next ``L`` press
        picks them up.  Repeated presses peel one layer at a time.
        """
        if self.current_tab == "agents":
            from ...models.agent_groups import build_agent_tree
            from ...models.fold_state import FoldLevel

            snapshots = [
                (
                    panel_agents,
                    registry,
                    build_agent_tree(
                        panel_agents,
                        fold_registry=registry,
                        mode=self._active_grouping_mode(),
                    ),
                )
                for _global_indices, panel_agents, registry in (
                    self._rendered_panel_fold_contexts()
                )
            ]
            changed = False
            seen_wf_keys: set[str] = set()
            for panel_agents, registry, entries in snapshots:
                for entry in entries:
                    if entry.kind == "group" and entry.group is not None:
                        if entry.group.is_collapsed:
                            if registry.expand(entry.group.group_key):
                                changed = True
                    elif entry.kind == "agent" and entry.agent_idx is not None:
                        agent = panel_agents[entry.agent_idx]
                        wf_key = self._get_workflow_key_for_agent(agent)
                        if wf_key is None or wf_key in seen_wf_keys:
                            continue
                        seen_wf_keys.add(wf_key)
                        if self._fold_manager.get(
                            wf_key
                        ) != FoldLevel.FULLY_EXPANDED and self._fold_manager.expand(
                            wf_key
                        ):
                            changed = True
            if changed:
                self._snap_focus_after_group_fold_change()
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        keys = self._get_focused_panel_workflow_keys()
        if not keys:
            return

        if self._fold_manager.expand_all(keys):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _collapse_all_folds(self) -> None:
        """Retreat the visible tree by one level (``H`` action).

        On the agents tab: walk the snapshot of currently-visible
        entries and apply a single-level collapse to each visible
        workflow fold.  Group banners collapse only at the deepest
        currently-expanded visible level.  Rows hidden behind a
        collapsed banner are not stepped (snapshot-at-start rule).
        Repeated presses peel one layer at a time.
        """
        if self.current_tab == "agents":
            from ...models.agent_groups import build_agent_tree
            from ...models.fold_state import FoldLevel

            snapshots = [
                (
                    panel_agents,
                    registry,
                    build_agent_tree(
                        panel_agents,
                        fold_registry=registry,
                        mode=self._active_grouping_mode(),
                    ),
                )
                for _global_indices, panel_agents, registry in (
                    self._rendered_panel_fold_contexts()
                )
            ]
            changed = False
            seen_wf_keys: set[str] = set()
            for panel_agents, registry, entries in snapshots:
                for entry in entries:
                    if entry.kind != "agent" or entry.agent_idx is None:
                        continue
                    agent = panel_agents[entry.agent_idx]
                    wf_key = self._get_workflow_key_for_agent(agent)
                    if wf_key is None or wf_key in seen_wf_keys:
                        continue
                    seen_wf_keys.add(wf_key)
                    if self._fold_manager.get(
                        wf_key
                    ) != FoldLevel.COLLAPSED and self._fold_manager.collapse(wf_key):
                        changed = True

                deepest_expanded_group_level = max(
                    (
                        entry.group.level
                        for entry in entries
                        if entry.kind == "group"
                        and entry.group is not None
                        and not entry.group.is_collapsed
                    ),
                    default=None,
                )
                for entry in entries:
                    if entry.kind != "group" or entry.group is None:
                        continue
                    if entry.group.level != deepest_expanded_group_level:
                        continue
                    if not entry.group.is_collapsed:
                        if registry.collapse(entry.group.group_key):
                            changed = True
            if changed:
                self._snap_focus_after_group_fold_change()
                self._refilter_agents()  # type: ignore[attr-defined]
            return

        keys = self._get_focused_panel_workflow_keys()
        if not keys:
            return

        if self._fold_manager.collapse_all(keys):
            self._refilter_agents()  # type: ignore[attr-defined]

    def _focused_axe_lumberjack_name(self) -> str | None:
        """Return the lumberjack name for the focused AXE row, if any.

        Chops resolve to their parent lumberjack so ``l``/``h`` on a chop
        operates on the enclosing fold.
        """
        from ...widgets.bgcmd_list import ChopItem, LumberjackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if not axe_items or not (0 <= self.current_idx < len(axe_items)):
            return None
        item = axe_items[self.current_idx]
        if isinstance(item, LumberjackItem):
            return item.name
        if isinstance(item, ChopItem):
            return item.lumberjack_name
        return None

    def _navigate_to_axe_lumberjack(self, name: str) -> None:
        """Move the AXE cursor to the row for ``name`` if it is visible."""
        from ...widgets.bgcmd_list import LumberjackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        for idx, item in enumerate(axe_items):
            if isinstance(item, LumberjackItem) and item.name == name:
                self.current_idx = idx
                return

    def _expand_axe_fold(self) -> None:
        """Expand the fold for the focused lumberjack (or chop's parent)."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        name = self._focused_axe_lumberjack_name()
        if name is None:
            return
        if axe_fold_manager.expand(f"lumberjack:{name}"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_axe_fold(self) -> None:
        """Collapse the fold for the focused lumberjack.

        If on a chop child, navigate to its parent lumberjack first so the
        cursor doesn't end up on a row that just disappeared.
        """
        from ...widgets.bgcmd_list import ChopItem

        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        name = self._focused_axe_lumberjack_name()
        if name is None:
            return

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            if isinstance(axe_items[self.current_idx], ChopItem):
                self._navigate_to_axe_lumberjack(name)

        if axe_fold_manager.collapse(f"lumberjack:{name}"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _expand_all_axe_folds(self) -> None:
        """Expand every lumberjack fold one level (``L`` on AXE)."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        names: list[str] = list(self._axe_lumberjack_names)  # type: ignore[attr-defined]
        if not names:
            return
        keys = [f"lumberjack:{n}" for n in names]
        if axe_fold_manager.expand_all(keys):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_all_axe_folds(self) -> None:
        """Collapse every lumberjack fold one level (``H`` on AXE).

        If the cursor is on a chop child, snap to its parent lumberjack
        first so the cursor stays on a still-visible row.
        """
        from ...widgets.bgcmd_list import ChopItem

        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        names: list[str] = list(self._axe_lumberjack_names)  # type: ignore[attr-defined]
        if not names:
            return

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            sel = axe_items[self.current_idx]
            if isinstance(sel, ChopItem):
                self._navigate_to_axe_lumberjack(sel.lumberjack_name)

        keys = [f"lumberjack:{n}" for n in names]
        if axe_fold_manager.collapse_all(keys):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _route_tools_detail_level(
        self, action: Literal["collapse", "expand", "min", "max"]
    ) -> bool:
        """Route fold keys to the Agents-tab Tools panel when it is active.

        Returns True when the key was handled by the Tools panel, even if the
        panel was already at the requested level.
        """
        if self.current_tab != "agents":
            return False
        try:
            from ...widgets import AgentDetail
            from ...widgets.tools_panel import ToolDetailLevel

            agent_detail = self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
        except Exception:
            return False
        if not agent_detail.is_tools_visible():
            return False

        if action == "expand":
            changed = agent_detail.expand_tools_detail()
        elif action == "collapse":
            changed = agent_detail.collapse_tools_detail()
        elif action == "max":
            changed = agent_detail.set_tools_detail_level(ToolDetailLevel.FULL)
        else:
            changed = agent_detail.set_tools_detail_level(ToolDetailLevel.COMPACT)
        if changed:
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                refresh_footer()
        return True

    def action_expand_or_layout(self) -> None:
        """Expand fold on agents/axe tab, or expand ChangeSpec group when grouped."""
        if self._route_tools_detail_level("expand"):
            return
        if self.current_tab == "agents":
            self._expand_fold()
        elif self.current_tab == "axe":
            self._expand_axe_fold()
        elif self.current_tab == "changespecs":
            if self._expand_changespec_group_fold():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]

    def action_hooks_or_collapse(self) -> None:
        """Collapse fold on agents/axe tab, collapse ChangeSpec group on ChangeSpecs tab."""
        if self._route_tools_detail_level("collapse"):
            return
        if self.current_tab == "agents":
            self._collapse_fold()
        elif self.current_tab == "axe":
            self._collapse_axe_fold()
        elif self.current_tab == "changespecs":
            if self._collapse_changespec_group_fold():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]

    def action_hooks_or_collapse_all(self) -> None:
        """Collapse all folds on agents/axe tab, collapse all ChangeSpec groups on ChangeSpecs tab."""
        if self._route_tools_detail_level("min"):
            return
        if self.current_tab == "agents":
            self._collapse_all_folds()
        elif self.current_tab == "axe":
            self._collapse_all_axe_folds()
        elif self.current_tab == "changespecs":
            if self._collapse_all_changespec_group_folds():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]

    def action_expand_all_folds(self) -> None:
        """Expand all workflow folds (agents/axe tab); ChangeSpecs tab expands all ChangeSpec groups."""
        if self._route_tools_detail_level("max"):
            return
        if self.current_tab == "agents":
            self._expand_all_folds()
        elif self.current_tab == "axe":
            self._expand_all_axe_folds()
        elif self.current_tab == "changespecs":
            if self._expand_all_changespec_group_folds():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]
