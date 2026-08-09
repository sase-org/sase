"""Quick agent entry points for current TUI context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.project_display_names import humanize_cl_name, project_display_name_for

if TYPE_CHECKING:
    from ....patch import Patch
    from ...modals import SelectionItem


class EntryQuickLaunchMixin:
    """Mixin providing quick launch entry points."""

    patches: list[Patch]
    current_idx: int
    _last_custom_agent_selection: SelectionItem | None

    if TYPE_CHECKING:

        def _vcs_prompt_prefix_or_notify(
            self, project_file: str, name: str
        ) -> str | None: ...

    def _start_agent_from_patch_quick(self) -> None:
        """Start agent from current Patch without Patch name modal.

        This is the quick version that skips CLNameInputModal entirely,
        going directly to the prompt input bar with a VCS prefix.
        """
        from ...modals import SelectionItem

        if not self.patches:
            self.notify("No Patches available", severity="warning")  # type: ignore[attr-defined]
            return

        patch = self.patches[self.current_idx]
        cl_name = patch.name
        display_name = humanize_cl_name(cl_name)
        prefix = self._vcs_prompt_prefix_or_notify(patch.file_path, display_name)
        if prefix is None:
            return

        # Save for Ctrl+Space repeat (so leader-Space selections are also available)
        selection = SelectionItem(
            display_name=display_name,
            item_type="cl",
            project_name=patch.project_basename,
            cl_name=cl_name,
        )
        from sase.ace.last_agent_selection import (
            save_last_agent_selection_if_launchable,
        )

        if save_last_agent_selection_if_launchable(selection):
            self._last_custom_agent_selection = selection

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=display_name,
            history_sort_key=cl_name,
        )

    def _start_agent_from_changespec_quick(self) -> None:  # legacy compatibility alias
        """Legacy alias for :meth:`_start_agent_from_patch_quick`."""
        self._start_agent_from_patch_quick()

    def _start_agent_from_agent_quick(self) -> None:
        """Start agent using the selected agent's project/Patch name.

        Uses the currently selected agent on the agents tab to derive
        the VCS prefix, similar to how leader-Space works on the Patches tab.
        """
        from ...modals import SelectionItem

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agents available", severity="warning")  # type: ignore[attr-defined]
            return
        cl_name = agent.cl_name
        project_name = Path(agent.project_file).parent.name
        display_name = (
            project_display_name_for(project_name)
            if agent.is_project_agent
            else humanize_cl_name(cl_name)
        )
        prefix = self._vcs_prompt_prefix_or_notify(agent.project_file, display_name)
        if prefix is None:
            return

        # Save for Ctrl+Space repeat
        selection = SelectionItem(
            display_name=display_name,
            item_type="project" if agent.is_project_agent else "cl",
            project_name=project_name,
            cl_name=cl_name if not agent.is_project_agent else None,
        )
        from sase.ace.last_agent_selection import (
            save_last_agent_selection_if_launchable,
        )

        if save_last_agent_selection_if_launchable(selection):
            self._last_custom_agent_selection = selection

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=display_name,
            history_sort_key=cl_name,
        )
