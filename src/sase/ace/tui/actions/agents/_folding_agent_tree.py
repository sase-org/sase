"""Structural agent-tree folding and left-navigation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ._folding_panels import AgentPanelFoldingMixin

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.fold_state import FoldStateManager

TabName = Literal["changespecs", "agents", "axe"]


@dataclass(frozen=True, slots=True)
class _AgentLeftNavigationTarget:
    """Validated immediate target for an Agents-tab ``h`` navigation."""

    kind: Literal["workflow", "family", "clan", "tribe"]
    index: int | None = None
    agent: Agent | None = None


@dataclass(frozen=True, slots=True)
class _AgentStructuralCollapseTarget:
    """The next workflow, family, or clan fold owned by Agents-tab ``H``."""

    fold_key: str
    kind: Literal["workflow", "family", "clan"]
    reanchor: bool = False
    binary: bool = False


class AgentStructuralFoldingMixin(AgentPanelFoldingMixin):
    """Manage structural agent-tree folding and left navigation."""

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]
    _current_group_key: tuple[str, ...] | None

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

    def _can_select_focused_tribe_panel(self) -> bool:
        """Return whether the focused split panel can become a whole selection."""
        panel_group = getattr(self, "_panel_group", None)
        panel_keys = getattr(panel_group, "panel_keys", ())
        focused_idx = getattr(panel_group, "focused_idx", -1)
        return bool(
            self.current_tab == "agents"
            and panel_group is not None
            and not getattr(self, "_agent_panels_grouped", False)
            and 0 <= focused_idx < len(panel_keys)
        )

    def _resolve_agent_left_navigation_target(
        self,
    ) -> _AgentLeftNavigationTarget | None:
        """Resolve the selected row/banner's validated immediate parent.

        The resolver stays entirely within the loaded Agents projection.  It
        accepts every validated workflow/family child -> owner edge plus direct
        member/family -> clan edges. A row or grouping banner reaches its tribe
        panel only after proving that it has no structural parent.
        """
        if self.current_tab != "agents" or not (
            0 <= self.current_idx < len(self._agents)
        ):
            return None

        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return None

        if self._current_group_key is not None:
            if self._can_select_focused_tribe_panel():
                return _AgentLeftNavigationTarget("tribe")
            return None

        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return None

        from ...models._agent_tree import agent_fold_key, agent_parent_fold_key

        parent_key = agent_parent_fold_key(selected)
        if parent_key is None:
            if (
                selected.is_child_row
                or selected.is_hidden_step
                or selected.step_type is not None
                or selected.is_pre_prompt_step
                or selected.tree_parent_key is not None
                or selected.tree_depth != 0
            ):
                return None
            selected_positions = sum(
                1 for candidate in self._agents if candidate is selected
            )
            own_key = agent_fold_key(selected)
            owner_matches = sum(
                1
                for candidate in self._agents
                if not candidate.is_child_row and agent_fold_key(candidate) == own_key
            )
            if selected_positions != 1 or (own_key is not None and owner_matches != 1):
                return None
            if self._can_select_focused_tribe_panel():
                return _AgentLeftNavigationTarget("tribe")
            return None

        return self._validated_agent_parent_target(selected, parent_key)

    def _validated_agent_parent_target(
        self,
        selected: Agent,
        parent_key: str,
    ) -> _AgentLeftNavigationTarget | None:
        """Validate and classify one canonical rendered-tree parent edge."""
        from ...models._agent_tree import agent_fold_key, tree_parent_lookup
        from ...models.agent_family_members import is_sequential_family_container

        parent = tree_parent_lookup(self._agents).get(parent_key)
        if parent is None or parent is selected:
            return None

        # Workflow-step rows in legacy/loader-shaped projections can repeat
        # their root's raw suffix. They alias the root's fold; they are not
        # competing structural owners. Navigation still requires one exact,
        # non-child owner and one occurrence of the canonical lookup result.
        parent_positions: list[int] = []
        owner_matches: list[tuple[int, Agent]] = []
        for index, candidate in enumerate(self._agents):
            if candidate is parent:
                parent_positions.append(index)
            if not candidate.is_child_row and agent_fold_key(candidate) == parent_key:
                owner_matches.append((index, candidate))
        if (
            len(parent_positions) != 1
            or len(owner_matches) != 1
            or owner_matches[0][1] is not parent
            or agent_fold_key(parent) != parent_key
        ):
            return None
        parent_index = parent_positions[0]

        # An explicit presentation edge is authoritative and must agree with
        # both persisted ancestry and rendered indentation. Loader-shaped
        # non-clan children may instead carry only parent_timestamp and retain
        # the legacy zero depth; a nonzero fallback depth must still be exact.
        if (
            selected.tree_parent_key is not None
            and selected.parent_timestamp is not None
            and selected.parent_timestamp != parent_key
        ):
            return None
        if selected.tree_parent_key is not None:
            if (
                selected.tree_parent_key != parent_key
                or selected.tree_depth != parent.tree_depth + 1
                or (
                    parent.is_clan_container
                    and (selected.is_child_row or selected.parent_timestamp is not None)
                )
                or (
                    not parent.is_clan_container
                    and (
                        not selected.is_child_row
                        or selected.parent_timestamp != parent_key
                    )
                )
            ):
                return None
        elif (
            parent.is_clan_container
            or not selected.is_child_row
            or selected.parent_timestamp != parent_key
            or selected.tree_depth not in {0, parent.tree_depth + 1}
        ):
            return None

        if parent.is_clan_container:
            kind: Literal["workflow", "family", "clan"] = "clan"
        elif is_sequential_family_container(parent):
            kind = "family"
        else:
            kind = "workflow"
        return _AgentLeftNavigationTarget(kind, parent_index, parent)

    def _navigate_agent_left(self) -> bool:
        """Move to the validated structural parent or containing tribe panel."""
        target = self._resolve_agent_left_navigation_target()
        if target is None:
            return False

        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        origin = self._agents[self.current_idx]
        if target.kind == "tribe":
            if self._current_group_key is None:
                arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
                if callable(arm_manual):
                    arm_manual(origin)
            activate_panel = getattr(self, "_activate_focused_panel", None)
            return bool(callable(activate_panel) and activate_panel())

        if target.index is None or target.agent is None:
            return False
        if origin.identity != target.agent.identity:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(origin)

        self._current_group_key = None
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]
        self.current_idx = target.index

        remember = getattr(self, "_remember_focused_panel_selection", None)
        if callable(remember):
            remember(("agent", target.index))
        acknowledge = getattr(self, "_acknowledge_agent_unread", None)
        if callable(acknowledge):
            acknowledge(target.agent)
        return True

    def _structural_fold_kind(
        self, fold_key: str
    ) -> Literal["workflow", "family", "clan"]:
        """Classify a canonical structural fold key for contextual labels."""
        from ...models._agent_tree import agent_fold_key
        from ...models.agent_family_members import is_sequential_family_container

        owner = next(
            (
                candidate
                for candidate in self._agents
                if agent_fold_key(candidate) == fold_key
            ),
            None,
        )
        if owner is not None and owner.is_clan_container:
            return "clan"
        if owner is not None and is_sequential_family_container(owner):
            return "family"
        return "workflow"

    def _resolve_agent_structural_collapse_target(
        self,
    ) -> _AgentStructuralCollapseTarget | None:
        """Resolve the highest-priority open structural fold for ``H``."""
        if self.current_tab != "agents" or self._current_group_key is not None:
            return None
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        if callable(resolve_panel) and resolve_panel() is not None:
            return None

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return None

        from ...models._agent_tree import agent_parent_fold_key
        from ...models.fold_state import FoldLevel

        fold_key = self._get_workflow_key_for_agent(agent)
        if (
            fold_key is not None
            and self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED
        ):
            level = self._fold_manager.get(fold_key)
            selected_is_child = (
                agent_parent_fold_key(agent) == fold_key and agent.is_child_row
            )
            reanchor = selected_is_child and (
                level == FoldLevel.EXPANDED
                or (level == FoldLevel.FULLY_EXPANDED and agent.is_hidden_step)
            )
            kind = self._structural_fold_kind(fold_key)
            return _AgentStructuralCollapseTarget(
                fold_key,
                kind,
                reanchor=reanchor,
                binary=kind == "clan",
            )

        clan_parent_key = agent_parent_fold_key(agent)
        if (
            agent.tree_depth == 1
            and clan_parent_key is not None
            and clan_parent_key.startswith("clan:")
            and self._fold_manager.get(clan_parent_key) != FoldLevel.COLLAPSED
        ):
            return _AgentStructuralCollapseTarget(
                clan_parent_key,
                "clan",
                reanchor=True,
                binary=True,
            )
        return None

    def _collapse_agent_structural_fold(self) -> bool:
        """Collapse one Agents workflow/family/clan target, if available."""
        target = self._resolve_agent_structural_collapse_target()
        if target is None:
            return False
        if target.reanchor:
            self._reanchor_to_fold_owner(target.fold_key)
        changed = (
            self._collapse_clan_fold(target.fold_key)
            if target.binary
            else self._fold_manager.collapse(target.fold_key)
        )
        if changed:
            self._refilter_agents()  # type: ignore[attr-defined]
        return changed


__all__ = ["AgentStructuralFoldingMixin", "TabName"]
