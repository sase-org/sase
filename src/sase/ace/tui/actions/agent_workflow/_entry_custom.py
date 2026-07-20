"""Custom-selection agent entry points."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.changespec.project_spec_path import preferred_project_spec_path
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from ...modals import SelectionItem


class EntryCustomMixin:
    """Mixin providing custom project/ChangeSpec launch entry points."""

    _last_custom_agent_selection: SelectionItem | None

    if TYPE_CHECKING:

        def _load_last_custom_agent_selection(
            self,
        ) -> tuple[SelectionItem | None, bool]: ...

        def _is_launchable_project(self, project_name: str) -> bool: ...

        def _clear_stale_last_custom_agent_selection(
            self, project_name: str
        ) -> None: ...

        def _vcs_prompt_prefix_or_notify(
            self, project_file: str, name: str
        ) -> str | None: ...

    def action_start_agent_from_changespec(self) -> None:
        """Repeat last +/Ctrl+Space agent selection."""
        last, stale_cleared = self._load_last_custom_agent_selection()
        if last is None:
            if not stale_cleared:
                self.notify("No previous +/Ctrl+Space selection", severity="warning")  # type: ignore[attr-defined]
            return
        self._start_custom_agent_from_selection(last)

    def action_start_agent_home(self) -> None:
        """Start a home-mode agent prompt."""
        self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]

    def action_start_last_vcs_xprompt_in_editor(self) -> None:
        """Open editor with the most recently used launchable VCS xprompt."""
        from sase.history.vcs_xprompt_mru import load_launchable_vcs_xprompt_mru
        from sase.xprompt import extract_project_from_vcs_tag

        prefixes = [p.strip() for p in load_launchable_vcs_xprompt_mru() if p.strip()]
        if not prefixes:
            self.notify("No previous VCS xprompt", severity="warning")  # type: ignore[attr-defined]
            return

        prefix = prefixes[0]
        initial_text = f"{prefix} "
        project_name = extract_project_from_vcs_tag(prefix)
        display_name = project_name or prefix
        history_sort_key = project_name or display_name

        self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
            initial_text=initial_text,
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

    def action_start_custom_agent(self) -> None:
        """Start a custom agent by selecting project or PR (works on all tabs)."""
        from ...modals import (
            ProjectSelectResult,
            SelectionItem,
        )
        from ...modals.project_select_modal import show_project_select_modal

        def on_project_select(result: ProjectSelectResult | None) -> None:
            if result is None:
                self.notify("Selection cancelled")  # type: ignore[attr-defined]
                return

            selection = result.selection
            open_in_editor = result.open_in_editor

            # Handle home directory selection
            if isinstance(selection, SelectionItem) and selection.item_type == "home":
                if open_in_editor:
                    self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
                else:
                    self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
                return

            # Determine selection type and details
            if isinstance(selection, str):
                # Custom name entered - no project file, use plain home mode
                if open_in_editor:
                    self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
                else:
                    self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
                return

            # Save for Ctrl+Space repeat
            from sase.ace.last_agent_selection import (
                save_last_agent_selection_if_launchable,
            )

            if save_last_agent_selection_if_launchable(selection):
                self._last_custom_agent_selection = selection
            self._start_custom_agent_from_selection(
                selection, open_in_editor=open_in_editor
            )

        show_project_select_modal(
            self,
            on_project_select,
            exclude_project_names={"home"},
        )

    def _start_custom_agent_from_selection(
        self,
        selection: SelectionItem,
        *,
        open_in_editor: bool = False,
    ) -> None:
        """Start a custom agent from a previously resolved selection.

        Args:
            selection: The project/ChangeSpec selection item.
            open_in_editor: Whether to open in editor instead of prompt bar.
        """
        project_name: str = selection.project_name
        if selection.item_type == "home":
            if open_in_editor:
                self._select_and_open_editor_for_home()  # type: ignore[attr-defined]
            else:
                self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            return

        if selection.item_type not in (
            "project",
            "cl",
        ) or not self._is_launchable_project(project_name):
            self._clear_stale_last_custom_agent_selection(project_name)
            return

        project_dir = str(sase_projects_dir() / project_name)
        project_file = preferred_project_spec_path(project_dir, project_name)

        if selection.item_type == "cl" and selection.cl_name:
            from sase.project_display_names import humanize_cl_name

            display_name = selection.selection_label or humanize_cl_name(
                selection.cl_name
            )
            prefix = self._vcs_prompt_prefix_or_notify(project_file, display_name)
            if prefix is None:
                return
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=selection.cl_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=selection.cl_name,
                )
        else:
            # Project selection. The prefix and bar label show the configured
            # project name (falling back to the directory key); identity uses
            # above keep ``selection.project_name``, and the history grouping
            # key stays the canonical directory key.
            from sase.project_display_names import project_display_name_for

            display_name = (
                selection.selection_label
                or selection.project_label
                or project_display_name_for(project_name)
            )
            prefix = self._vcs_prompt_prefix_or_notify(project_file, display_name)
            if prefix is None:
                return
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=project_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=display_name,
                    history_sort_key=project_name,
                )
