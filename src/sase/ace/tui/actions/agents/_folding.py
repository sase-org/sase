"""Agent fold state management methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
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

    def _expand_fold(self) -> None:
        """Expand the fold for the selected workflow (one level)."""
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return

        agent = self._agents[self.current_idx]
        key = self._get_workflow_key_for_agent(agent)
        if key is None:
            return

        if self._fold_manager.expand(key):
            self._load_agents()  # type: ignore[attr-defined]

    def _collapse_fold(self) -> None:
        """Collapse the fold for the selected workflow (one level).

        When collapsing and selected agent is a child, navigate selection to parent.
        """
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return

        agent = self._agents[self.current_idx]
        key = self._get_workflow_key_for_agent(agent)
        if key is None:
            return

        # If selected agent is a child and we're collapsing to COLLAPSED,
        # navigate selection to parent before reloading
        if agent.is_workflow_child and agent.parent_timestamp:
            from ...models.fold_state import FoldLevel

            if self._fold_manager.get(key) == FoldLevel.EXPANDED:
                # Will collapse to COLLAPSED - find parent and select it
                for idx, a in enumerate(self._agents):
                    if (
                        a.raw_suffix == agent.parent_timestamp
                        and not a.is_workflow_child
                    ):
                        self.current_idx = idx
                        break

        if self._fold_manager.collapse(key):
            self._load_agents()  # type: ignore[attr-defined]

    def _expand_all_folds(self) -> None:
        """Expand all workflow folds one level."""
        keys = self._get_all_workflow_keys()
        if not keys:
            return

        if self._fold_manager.expand_all(keys):
            self._load_agents()  # type: ignore[attr-defined]

    def _collapse_all_folds(self) -> None:
        """Collapse all workflow folds one level."""
        keys = self._get_all_workflow_keys()
        if not keys:
            return

        if self._fold_manager.collapse_all(keys):
            self._load_agents()  # type: ignore[attr-defined]

    def _expand_axe_fold(self) -> None:
        """Expand the AXE jack fold."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        if axe_fold_manager.expand("axe"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_axe_fold(self) -> None:
        """Collapse the AXE jack fold.

        If on a jack child, navigate to parent first.
        """
        from ...widgets.bgcmd_list import JackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            if isinstance(axe_items[self.current_idx], JackItem):
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
