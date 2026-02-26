"""Agent start entry points and leader mode for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ._types import PromptContext, TabName

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...models import Agent
    from ...modals import SelectionItem


def _vcs_prompt_prefix(project_file: str, name: str) -> str:
    """Build a VCS prompt prefix like ``#gh:name `` or ``#hg:name ``.

    Args:
        project_file: Path to the project ``.gp`` file.
        name: Project or CL name to embed in the prefix.

    Returns:
        A string such as ``"#gh:my_cl "`` or ``"#hg:my_cl "``.
    """
    from sase.workspace_provider import detect_workflow_type

    workflow_type = detect_workflow_type(project_file)
    return f"#{workflow_type}:{name} "


class EntryPointsMixin:
    """Mixin providing agent start entry points and leader mode."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _agents: list[Agent]
    _leader_mode_active: bool

    # State for prompt input
    _prompt_context: PromptContext | None = None
    # State for bulk agent runs
    _bulk_changespecs: list[ChangeSpec] | None = None
    # State for repeat-last-@/<space> selection
    _last_custom_agent_selection: SelectionItem | None = None

    def action_start_agent_from_changespec(self) -> None:
        """Start agent from current ChangeSpec (CLs tab only, bound to space)."""
        if self.current_tab != "changespecs":
            return

        if self.marked_indices:
            self._start_agents_from_marked()
        else:
            self._start_agent_from_changespec_quick()

    def action_start_leader_mode(self) -> None:
        """Enter leader mode for quick shortcuts (bound to ,)."""
        self._leader_mode_active = True
        self._update_leader_footer(current_tab=self.current_tab)

    def _handle_leader_key(self, key: str) -> bool:
        """Handle a key press in leader mode.

        Args:
            key: The key that was pressed.

        Returns:
            True if the key was handled, False otherwise.
        """
        # Always exit leader mode
        self._leader_mode_active = False

        if key == "escape":
            # Cancel silently and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == "exclamation_mark":
            if self.current_tab != "changespecs":
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._start_bgcmd_from_changespec()  # type: ignore[attr-defined]
            return True

        if key == "r":
            self.action_show_runners()  # type: ignore[attr-defined]
            return True

        if key == "space":
            last = self._last_custom_agent_selection
            if last is None:
                from sase.ace.last_agent_selection import load_last_agent_selection

                last = load_last_agent_selection()
                if last is not None:
                    self._last_custom_agent_selection = last
            if last is None:
                self.notify("No previous @/<space> selection", severity="warning")  # type: ignore[attr-defined]
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._start_custom_agent_from_selection(last)
            return True

        # Unknown key - just exit mode and restore footer
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

    def _start_agent_from_changespec_quick(self) -> None:
        """Start agent from current ChangeSpec without CL name modal.

        This is the quick version that skips CLNameInputModal entirely,
        going directly to the prompt input bar with a VCS prefix.
        """
        from ...modals import SelectionItem

        if not self.changespecs:
            self.notify("No ChangeSpecs available", severity="warning")  # type: ignore[attr-defined]
            return

        changespec = self.changespecs[self.current_idx]
        cl_name = changespec.name
        prefix = _vcs_prompt_prefix(changespec.file_path, cl_name)

        # Save for ,<space> repeat (so <space> selections are also available)
        self._last_custom_agent_selection = SelectionItem(
            display_name=cl_name,
            item_type="cl",
            project_name=changespec.project_basename,
            cl_name=cl_name,
        )
        from sase.ace.last_agent_selection import save_last_agent_selection

        save_last_agent_selection(self._last_custom_agent_selection)

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=cl_name,
            history_sort_key=cl_name,
        )

    def _update_leader_footer(self, *, current_tab: TabName = "changespecs") -> None:
        """Update the footer to show leader mode bindings.

        Args:
            current_tab: The currently active tab name.
        """
        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_leader_bindings(current_tab=current_tab)
        except Exception:
            pass

    def action_start_custom_agent(self) -> None:
        """Start a custom agent by selecting project or CL (works on all tabs)."""
        from ...modals import (
            ProjectSelectModal,
            ProjectSelectResult,
            SelectionItem,
        )

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

            # Save for ,<space> repeat
            self._last_custom_agent_selection = selection
            from sase.ace.last_agent_selection import save_last_agent_selection

            save_last_agent_selection(selection)
            self._start_custom_agent_from_selection(
                selection, open_in_editor=open_in_editor
            )

        self.push_screen(ProjectSelectModal(), on_project_select)  # type: ignore[attr-defined]

    def _start_custom_agent_from_selection(
        self,
        selection: SelectionItem,
        *,
        open_in_editor: bool = False,
    ) -> None:
        """Start a custom agent from a previously resolved selection.

        Args:
            selection: The project/CL selection item.
            open_in_editor: Whether to open in editor instead of prompt bar.
        """
        project_name: str = selection.project_name
        project_file = os.path.expanduser(
            f"~/.sase/projects/{project_name}/{project_name}.gp"
        )

        if selection.item_type == "cl" and selection.cl_name:
            prefix = _vcs_prompt_prefix(project_file, selection.cl_name)
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=selection.cl_name,
                    history_sort_key=selection.cl_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=selection.cl_name,
                    history_sort_key=selection.cl_name,
                )
        else:
            # Project selection
            prefix = _vcs_prompt_prefix(project_file, project_name)
            if open_in_editor:
                self._select_and_open_editor_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=project_name,
                    history_sort_key=project_name,
                )
            else:
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prefix,
                    display_name=project_name,
                    history_sort_key=project_name,
                )

    def _start_agents_from_marked(self) -> None:
        """Start agents for all marked ChangeSpecs.

        Shows a single prompt input bar. The prompt will be used for all
        marked items.
        """
        if not self.marked_indices:
            self.notify("No marked ChangeSpecs", severity="warning")  # type: ignore[attr-defined]
            return

        # Collect all marked ChangeSpecs (sorted by index for consistency)
        self._bulk_changespecs = [
            self.changespecs[idx]
            for idx in sorted(self.marked_indices)
            if idx < len(self.changespecs)
        ]

        if not self._bulk_changespecs:
            self.notify("No valid marked ChangeSpecs", severity="warning")  # type: ignore[attr-defined]
            self._bulk_changespecs = None
            return

        # Use first changespec for prompt context (history, etc.)
        first_cs = self._bulk_changespecs[0]
        count = len(self._bulk_changespecs)

        self.notify(f"Running agent on {count} marked CL(s)")  # type: ignore[attr-defined]

        self._show_prompt_input_bar(  # type: ignore[attr-defined]
            first_cs.project_basename,
            cl_name=first_cs.name,
            update_target=first_cs.name,
            history_sort_key=first_cs.name,
        )
