"""Agent start entry points and leader mode for the ace TUI app."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ._types import PromptContext, TabName

if TYPE_CHECKING:
    from ....changespec import ChangeSpec
    from ...activity_log import ActivityLog
    from ...keymaps import KeymapRegistry
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
    _keymap_registry: KeymapRegistry
    _activity_log: ActivityLog
    _inactive_seconds: int

    # State for prompt input
    _prompt_context: PromptContext | None = None
    # State for bulk agent runs
    _bulk_changespecs: list[ChangeSpec] | None = None
    # State for repeat-last-@/<space> selection
    _last_custom_agent_selection: SelectionItem | None = None

    def _show_activity_dashboard(self) -> None:
        """Show the Activity Dashboard modal."""
        from ...modals import ActivityModal

        self.push_screen(ActivityModal(self._activity_log, self._inactive_seconds))  # type: ignore[attr-defined]

    def action_start_agent_from_changespec(self) -> None:
        """Repeat last @/<space> agent selection (bound to space)."""
        last = self._last_custom_agent_selection
        if last is None:
            from sase.ace.last_agent_selection import load_last_agent_selection

            last = load_last_agent_selection()
            if last is not None:
                self._last_custom_agent_selection = last
        if last is None:
            self.notify("No previous @/<space> selection", severity="warning")  # type: ignore[attr-defined]
            return
        self._start_custom_agent_from_selection(last)

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

        leader_keys = self._keymap_registry.leader_mode.keys

        if key == leader_keys["run_cmd"]:
            if self.current_tab != "changespecs":
                self._refresh_current_tab()  # type: ignore[attr-defined]
                return True
            self._start_bgcmd_from_changespec()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["runners"]:
            self.action_show_runners()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_mentors"]:
            if self.current_tab == "changespecs":
                self.action_kill_mentors()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_home"]:
            # Shortcut for @ → ~ (home): skip the ProjectSelectModal
            self._show_prompt_input_bar_for_home()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["agent_from_cl"]:
            if self.current_tab == "changespecs":
                if self.marked_indices:
                    self._start_agents_from_marked()
                else:
                    self._start_agent_from_changespec_quick()
            elif self.current_tab == "agents":
                self._start_agent_from_agent_quick()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["kill_and_edit"]:
            if self.current_tab == "agents":
                self._kill_and_edit_agent()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["activity_info"]:
            self._show_activity_dashboard()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["clear_comments"]:
            if self.current_tab == "changespecs":
                self._clear_changespec_comments()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == leader_keys["jump_to_notification"]:
            if self.current_tab == "agents":
                self._jump_to_agent_notification()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
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

        # Save for <space> repeat (so ,<space> selections are also available)
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

    def _start_agent_from_agent_quick(self) -> None:
        """Start agent using the selected agent's project/CL name.

        Uses the currently selected agent on the agents tab to derive
        the VCS prefix, similar to how ,<space> works on the CLs tab.
        """
        from pathlib import Path

        from ...modals import SelectionItem

        if not self._agents:
            self.notify("No agents available", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]
        cl_name = agent.cl_name
        project_name = Path(agent.project_file).parent.name
        prefix = _vcs_prompt_prefix(agent.project_file, cl_name)

        # Save for <space> repeat
        self._last_custom_agent_selection = SelectionItem(
            display_name=cl_name,
            item_type="project" if agent.is_project_agent else "cl",
            project_name=project_name,
            cl_name=cl_name if not agent.is_project_agent else None,
        )
        from sase.ace.last_agent_selection import save_last_agent_selection

        save_last_agent_selection(self._last_custom_agent_selection)

        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=prefix,
            display_name=cl_name,
            history_sort_key=cl_name,
        )

    def _clear_changespec_comments(self) -> None:
        """Remove the COMMENTS field, kill running CRS agents, and delete proposals."""
        if not self.changespecs:
            self.notify("No ChangeSpecs available", severity="warning")  # type: ignore[attr-defined]
            return

        changespec = self.changespecs[self.current_idx]
        if not changespec.comments:
            self.notify("No comments to clear", severity="warning")  # type: ignore[attr-defined]
            return

        # Kill any running CRS agents
        import os
        import signal

        from sase.ace.changespec import extract_pid_from_agent_suffix

        killed_agents = 0
        for comment in changespec.comments:
            if (
                comment.suffix_type == "running_agent"
                and comment.suffix
                and comment.suffix.startswith("crs")
            ):
                pid = extract_pid_from_agent_suffix(comment.suffix)
                if pid is not None:
                    try:
                        os.killpg(pid, signal.SIGTERM)
                        killed_agents += 1
                    except (ProcessLookupError, PermissionError):
                        pass

        # Delete any CRS proposal commits associated with comments
        deleted_proposals = 0
        if changespec.commits:
            from sase.change_actions import delete_proposal_entry

            crs_proposals = [
                c
                for c in changespec.commits
                if c.is_proposed and c.note.startswith("[crs")
            ]
            for entry in crs_proposals:
                if entry.diff:
                    try:
                        diff_path = os.path.expanduser(entry.diff)
                        if os.path.isfile(diff_path):
                            os.remove(diff_path)
                    except OSError:
                        pass
                if entry.proposal_letter:
                    if delete_proposal_entry(
                        changespec.file_path,
                        changespec.name,
                        entry.number,
                        entry.proposal_letter,
                    ):
                        deleted_proposals += 1

        from sase.ace.comments.operations import update_changespec_comments_field

        ok = update_changespec_comments_field(
            changespec.file_path, changespec.name, None
        )
        if ok:
            changespec.comments = None
            if changespec.commits and deleted_proposals:
                changespec.commits = [
                    c
                    for c in changespec.commits
                    if not (c.is_proposed and c.note.startswith("[crs"))
                ]
            msg = f"Cleared COMMENTS for {changespec.name}"
            details = []
            if killed_agents:
                details.append(f"killed {killed_agents} CRS agent(s)")
            if deleted_proposals:
                details.append(f"deleted {deleted_proposals} CRS proposal(s)")
            if details:
                msg += f" ({', '.join(details)})"
            self.notify(msg)  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to clear COMMENTS for {changespec.name}", severity="error"
            )

    def _update_leader_footer(self, *, current_tab: TabName = "changespecs") -> None:
        """Update the footer to show leader mode bindings.

        Args:
            current_tab: The currently active tab name.
        """
        from ...widgets import KeybindingFooter

        has_comments = False
        if current_tab == "changespecs" and self.changespecs:
            cs = self.changespecs[self.current_idx]
            has_comments = bool(cs.comments)

        has_notification = False
        if current_tab == "agents" and self._agents:
            if 0 <= self.current_idx < len(self._agents):
                agent = self._agents[self.current_idx]
                has_notification = agent.status in ("PLANNING", "QUESTION")

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_leader_bindings(
                current_tab=current_tab,
                has_comments=has_comments,
                has_notification=has_notification,
            )
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

    def _kill_and_edit_agent(self) -> None:
        """Kill the selected agent, then open its prompt in the editor for re-launch.

        Reads the agent's raw xprompt content, kills the agent (with
        confirmation if running), opens the prompt in ``$EDITOR``, and
        launches a new agent with the edited content.
        """
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        agent = self._agents[self.current_idx]

        # Capture agent info before killing (agent is removed from _agents on kill)
        agent_project_file = agent.project_file
        agent_cl_name = agent.cl_name
        agent_is_project_agent = agent.is_project_agent
        raw_prompt = agent.get_raw_xprompt_content()

        if raw_prompt is None:
            self.notify("No prompt found for this agent", severity="warning")  # type: ignore[attr-defined]
            return

        from ..agents._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES or agent.pid is None:
            # No confirmation needed - dismiss and open editor
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            self._edit_and_relaunch_agent(
                raw_prompt, agent_project_file, agent_cl_name, agent_is_project_agent
            )
            return

        # Build description for confirmation dialog
        desc_parts = [f"Type: {agent.agent_type.value}"]
        desc_parts.append(f"CL: {agent.cl_name}")
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_agent(agent)  # type: ignore[attr-defined]
                self._edit_and_relaunch_agent(
                    raw_prompt,
                    agent_project_file,
                    agent_cl_name,
                    agent_is_project_agent,
                )

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        """Open agent prompt in editor and relaunch on save.

        Args:
            raw_prompt: The agent's raw xprompt content.
            project_file: The killed agent's project file path.
            cl_name: The killed agent's CL name.
            is_project_agent: Whether the killed agent was a project-level agent.
        """
        from pathlib import Path

        from sase.sase_utils import generate_timestamp

        from ...modals import SelectionItem

        project_name = Path(project_file).parent.name
        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"

        # Save for <space> repeat
        self._last_custom_agent_selection = SelectionItem(
            display_name=cl_name,
            item_type="project" if is_project_agent else "cl",
            project_name=project_name,
            cl_name=cl_name if not is_project_agent else None,
        )
        from sase.ace.last_agent_selection import save_last_agent_selection

        save_last_agent_selection(self._last_custom_agent_selection)

        # Set up prompt context (home mode, same as ,<space>)
        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=os.path.expanduser("~/.sase/projects/home/home.gp"),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=cl_name,
            display_name=cl_name,
            update_target="",
            is_home_mode=True,
        )

        # Open editor with the agent's prompt
        edited_prompt = self._open_editor_for_agent_prompt(raw_prompt)  # type: ignore[attr-defined]
        if edited_prompt:
            self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
        else:
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._prompt_context = None

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
