"""Agent fold state management methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from ._fold_scope import focused_panel_fold_registry, panel_fold_registry
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.agent_panels import PanelKey
    from ...models.fold_state import FoldStateManager
    from ...models.group_fold import GroupFoldRegistry

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]
_FOCUSED_PANEL = object()


class AgentFoldingMixin:
    """Mixin providing agent fold state management methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _agents: list[Agent]
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _collapsed_panel_keys: set[PanelKey]

    def _persist_group_fold_change(
        self,
        group_key: GroupKey,
        *,
        collapsed: bool,
        panel_key: PanelKey | object = _FOCUSED_PANEL,
    ) -> None:
        record = getattr(self, "_record_agents_group_fold_change", None)
        if callable(record):
            if panel_key is _FOCUSED_PANEL:
                record(group_key, collapsed=collapsed)
            else:
                record(
                    group_key,
                    collapsed=collapsed,
                    panel_key=cast("PanelKey", panel_key),
                )

    def _persist_panel_fold_change(
        self,
        panel_key: PanelKey,
        *,
        collapsed: bool,
    ) -> None:
        record = getattr(self, "_record_agents_panel_fold_change", None)
        if callable(record):
            record(panel_key, collapsed=collapsed)

    def _get_workflow_key_for_agent(self, agent: Agent) -> str | None:
        """Get the fold state key targeted by actions on an agent row.

        Args:
            agent: The agent to get the key for.

        Returns:
            The row's owned descendant key, its immediate parent's key when
            selected as a child, or ``None`` when neither edge is foldable.
        """
        from ...models._agent_tree import agent_fold_key, agent_parent_fold_key

        if agent.is_clan_container:
            return agent_fold_key(agent)
        fold_key = agent_fold_key(agent)
        if fold_key in self._fold_counts:
            return fold_key
        if agent.is_child_row:
            return agent_parent_fold_key(agent)
        return None

    def _reanchor_to_fold_owner(self, fold_key: str) -> None:
        """Move selection to the visible row that owns ``fold_key``."""
        from ...models._agent_tree import agent_fold_key

        for idx, candidate in enumerate(self._agents):
            if agent_fold_key(candidate) == fold_key:
                self.current_idx = idx
                return

    def _collapse_clan_fold(self, fold_key: str) -> bool:
        """Collapse a clan's binary outer fold in a single action."""
        from ...models.fold_state import FoldLevel

        changed = False
        while self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
            if not self._fold_manager.collapse(fold_key):
                break
            changed = True
        return changed

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
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    # First ``l`` expands a collapsed selected panel but keeps
                    # whole-panel focus; a second ``l`` descends into it.
                    self._expanded_panel_focus = True
                    if self._expand_agent_panel(panel_focus.panel_key):
                        self._refresh_agents_display(  # type: ignore[attr-defined]
                            list_changed=True
                        )
                    return
                exit_focus = getattr(self, "_exit_expanded_panel_focus", None)
                if callable(exit_focus):
                    exit_focus()
                return

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
                    self._persist_group_fold_change(group_key, collapsed=False)
                return

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is None:
                return
            wf_key = self._get_workflow_key_for_agent(agent)
            if wf_key is None:
                return
            if agent.is_clan_container:
                from ...models.fold_state import FoldLevel

                if self._fold_manager.get(wf_key) != FoldLevel.COLLAPSED:
                    return
            if self._fold_manager.expand(wf_key):
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

        On Agents, ``h`` walks only structural agent/family/clan folds. Once
        none remain (or a collapsed group banner is selected), it promotes
        focus to the enclosing tribe panel. Grouping-strategy folds belong to
        ``H`` and are handled by :meth:`_collapse_group_fold`.
        """
        if self.current_tab == "agents":
            from ...models._agent_tree import agent_parent_fold_key
            from ...models.fold_state import FoldLevel

            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            panel_focus = resolve_panel() if callable(resolve_panel) else None
            if panel_focus is not None:
                if panel_focus.collapsed:
                    self.notify(  # type: ignore[attr-defined]
                        "Panel is already collapsed", timeout=1.5
                    )
                else:
                    self._collapse_focused_panel()
                return

            agent = self._get_selected_agent()  # type: ignore[attr-defined]
            if agent is not None and self._current_group_key is None:
                key = self._get_workflow_key_for_agent(agent)
                if (
                    key is not None
                    and self._fold_manager.get(key) != FoldLevel.COLLAPSED
                ):
                    level = self._fold_manager.get(key)
                    selected_parent_key = agent_parent_fold_key(agent)
                    selected_is_child = (
                        selected_parent_key == key and agent.is_child_row
                    )
                    if selected_is_child and (
                        level == FoldLevel.EXPANDED
                        or (level == FoldLevel.FULLY_EXPANDED and agent.is_hidden_step)
                    ):
                        self._reanchor_to_fold_owner(key)

                    changed = (
                        self._collapse_clan_fold(key)
                        if agent.is_clan_container
                        else self._fold_manager.collapse(key)
                    )
                    if changed:
                        self._refilter_agents()  # type: ignore[attr-defined]
                        return

                # Once a direct member's own fold is collapsed, walk up to
                # the enclosing clan before falling through to group folds.
                clan_parent_key = agent_parent_fold_key(agent)
                if (
                    agent.tree_depth == 1
                    and clan_parent_key is not None
                    and clan_parent_key.startswith("clan:")
                    and self._fold_manager.get(clan_parent_key) != FoldLevel.COLLAPSED
                ):
                    self._reanchor_to_fold_owner(clan_parent_key)
                    if self._collapse_clan_fold(clan_parent_key):
                        self._refilter_agents()  # type: ignore[attr-defined]
                        return

            activate_panel = getattr(self, "_activate_focused_panel", None)
            if callable(activate_panel):
                activate_panel()
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

    def _collapse_group_fold(self) -> None:
        """Collapse the enclosing Agents grouping-strategy fold with ``H``."""
        if self.current_tab != "agents":
            return
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return

        if self._current_group_key is not None:
            cur_key: GroupKey = tuple(self._current_group_key)
            registry = focused_panel_fold_registry(self)
            if len(cur_key) > 1 and registry.is_collapsed(cur_key):
                parent_key: GroupKey = cur_key[:-1]
                if registry.collapse(parent_key):
                    self._current_group_key = parent_key
                    self._refilter_agents()  # type: ignore[attr-defined]
                    self._persist_group_fold_change(parent_key, collapsed=True)
                return
            if registry.collapse(cur_key):
                self._refilter_agents()  # type: ignore[attr-defined]
                self._persist_group_fold_change(cur_key, collapsed=True)
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return
        l1_key, l0_key = self._focused_group_keys()
        target = l1_key or l0_key
        registry = focused_panel_fold_registry(self)
        if target is not None and registry.collapse(target):
            self._current_group_key = target
            self._snap_focus_after_group_fold_change()
            self._refilter_agents()  # type: ignore[attr-defined]
            self._persist_group_fold_change(target, collapsed=True)

    def _collapse_focused_panel(self) -> None:
        """Collapse the focused tag panel while retaining its detail context."""
        if self.current_tab != "agents":
            return
        panel_group = getattr(self, "_panel_group", None)
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or len(panel_group.panel_keys) <= 1
        ):
            return

        collapsed_keys: set[PanelKey] | None = getattr(
            self, "_collapsed_panel_keys", None
        )
        if collapsed_keys is None:
            collapsed_keys = set()
            self._collapsed_panel_keys = collapsed_keys
        focused_key = panel_group.focused_key
        if focused_key in collapsed_keys:
            return

        collapsed_keys.add(focused_key)
        self._expanded_panel_focus = False
        self._current_group_key = None
        self.current_attempt_number = None
        global_indices, _panel_agents = rendered_panel_slice(self, focused_key)
        if global_indices:
            self.current_idx = global_indices[0]
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self._persist_panel_fold_change(focused_key, collapsed=True)

    def _expand_agent_panel(self, panel_key: PanelKey) -> bool:
        """Expand one whole panel without selecting or refreshing it."""
        panel_group = getattr(self, "_panel_group", None)
        collapsed_keys: set[PanelKey] = getattr(self, "_collapsed_panel_keys", set())
        if (
            panel_group is None
            or getattr(self, "_agent_panels_grouped", False)
            or panel_key not in panel_group.panel_keys
            or panel_key not in collapsed_keys
        ):
            return False

        collapsed_keys.discard(panel_key)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _expand_focused_panel(self) -> None:
        """Expand the focused tag panel and select its first rendered row."""
        if self.current_tab != "agents":
            return
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return

        focused_key = panel_group.focused_key
        if not self._expand_agent_panel(focused_key):
            return
        self._expanded_panel_focus = False
        stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        if stops:
            self._focus_panel_navigation_stop(stops[0])  # type: ignore[attr-defined]
        else:
            self._current_group_key = None
            keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
            self._snap_current_idx_to_focused_panel(  # type: ignore[attr-defined]
                keys_per_agent,
                focused_key,
            )
        self.current_attempt_number = None
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

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
        """Collapse an Agents group or all folds/groups on the other tabs."""
        if self._route_tools_detail_level("min"):
            return
        if self.current_tab == "agents":
            self._collapse_group_fold()
        elif self.current_tab == "axe":
            self._collapse_all_axe_folds()
        elif self.current_tab == "changespecs":
            if self._collapse_all_changespec_group_folds():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]

    def action_expand_all_folds(self) -> None:
        """Expand an agent panel or all folds/groups on the other tabs."""
        if self._route_tools_detail_level("max"):
            return
        if self.current_tab == "agents":
            self._expand_focused_panel()
        elif self.current_tab == "axe":
            self._expand_all_axe_folds()
        elif self.current_tab == "changespecs":
            if self._expand_all_changespec_group_folds():  # type: ignore[attr-defined]
                self._refresh_display()  # type: ignore[attr-defined]
