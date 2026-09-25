"""Workflow and agent-retry actions for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..modals import WorkflowSelectModal
from ._base_types import BaseActionsHost

if TYPE_CHECKING:
    from ...patch import Patch


class BaseWorkflowActionsMixin(BaseActionsHost):
    """Mixin providing workflow run and agent retry actions."""

    def action_run_workflow(self) -> None:
        """Run a Patch workflow or an Axe run/re-run.

        Agents retry lives on :meth:`action_agents_retry`. This method still
        forwards the Agents branch so programmatic callers keep working.
        """
        # On axe tab, dispatch to re-run for done bgcmds or to manual chop run
        # for chop rows. Other rows (lumberjacks, running bgcmds) are no-ops.
        if self.current_tab == "services":
            from ..widgets.bgcmd_list import BgCmdItem, ChopItem, ServiceProcItem

            items = getattr(self, "_axe_items", [])
            idx = self.current_idx
            if 0 <= idx < len(items):
                item = items[idx]
                if isinstance(item, BgCmdItem):
                    bgcmd_info = dict(self._bgcmd_slots).get(item.slot)  # type: ignore[attr-defined]
                    if bgcmd_info is not None and not bgcmd_info.running:
                        self._rerun_bgcmd(item.slot)  # type: ignore[attr-defined]
                elif isinstance(item, ServiceProcItem):
                    self._restart_selected_service_proc()  # type: ignore[attr-defined]
                elif isinstance(item, ChopItem):
                    self._run_selected_chop()  # type: ignore[attr-defined]
            return

        if self.current_tab == "agents":
            self._retry_selected_agent()
            return

        # Only run on patches tab
        if self.current_tab != "artifacts":
            return

        from ...operations import get_available_workflows

        if not self.patches:
            return

        patch = self.patches[self.current_idx]
        workflows = get_available_workflows(patch)

        if not workflows:
            self.notify("No workflows available", severity="warning")  # type: ignore[attr-defined]
            return

        if len(workflows) == 1:
            # Single workflow, run directly
            self._run_workflow(patch, 0)
        else:
            # Multiple workflows, show selection modal

            def on_dismiss(workflow_idx: int | None) -> None:
                if workflow_idx is not None:
                    self._run_workflow(patch, workflow_idx)

            self.push_screen(WorkflowSelectModal(workflows), on_dismiss)  # type: ignore[attr-defined]

    def action_agents_refresh(self) -> None:
        """Refresh Agents, or open the Refresh panel when that flag is on."""
        self.action_refresh()  # type: ignore[attr-defined]

    def action_agents_retry(self) -> None:
        """Retry the selected local or remote agent."""
        self._retry_selected_agent()

    def _retry_selected_agent(self) -> None:
        """Retry the focused Agents row via the existing local/remote paths."""
        from .agents._remote_lifecycle import is_remote_fleet_agent

        get_selected = getattr(self, "_get_selected_agent", None)
        if callable(get_selected):
            selected_agent = get_selected()
            if is_remote_fleet_agent(selected_agent):
                self.action_retry_remote_agent()  # type: ignore[attr-defined]
                return
        self._retry_edit_agent()  # type: ignore[attr-defined]

    def _run_workflow(self, patch: Patch, workflow_index: int) -> None:
        """Run a specific workflow."""
        from ...handlers import handle_run_workflow
        from .._workflow_context import WorkflowContext

        def run_handler() -> tuple[list[Patch], int]:
            ctx = WorkflowContext()
            return handle_run_workflow(
                ctx,  # type: ignore[arg-type]
                patch,
                self.patches,
                self.current_idx,
                workflow_index,
            )

        with self.suspend():  # type: ignore[attr-defined]
            try:
                new_patches, new_idx = run_handler()
            except Exception as e:
                self.notify(f"Workflow error: {e}", severity="error")  # type: ignore[attr-defined]
                self._reload_and_reposition()  # type: ignore[attr-defined]
                return

        self._reload_and_reposition()  # type: ignore[attr-defined]
