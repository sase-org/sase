"""Agent start entry points for the ace TUI app."""

from __future__ import annotations

import os
import re
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


def _format_prompt_with_prettier(text: str, screen_width: int) -> str:
    """Format prompt text with prettier for display in the prompt input bar.

    Uses the same ``prettier --prose-wrap always`` invocation as
    :meth:`PromptTextArea._format_with_prettier` for auto-wrap.

    Args:
        text: The prompt text to format.
        screen_width: The terminal screen width for calculating wrap width.

    Returns:
        The formatted text, or the original text if prettier fails.
    """
    import subprocess

    # Approximate the PromptTextArea wrap width:
    # screen - border (2) - gutter - scrollbar (2) - cursor (1)
    line_count = text.count("\n") + 1
    gutter_width = len(str(max(line_count, 2))) + 2
    wrap_width = max(screen_width - 2 - gutter_width - 2 - 1, 1)

    try:
        result = subprocess.run(
            [
                "prettier",
                "--parser",
                "markdown",
                "--prose-wrap",
                "always",
                "--print-width",
                str(wrap_width),
            ],
            input=text.encode(),
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            formatted = result.stdout.decode()
            if formatted.endswith("\n"):
                formatted = formatted[:-1]
            return formatted
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return text


def _rewrite_retry_prompt_name(raw_prompt: str, retry_name: str) -> str:
    """Replace or prepend the top-level prompt name directive for retry."""
    from sase.xprompt._directive_types import (
        _DIRECTIVE_ALIASES,
        _DIRECTIVE_PATTERN,
    )
    from sase.xprompt._disabled_regions import (
        protect_disabled_regions,
        unprotect_disabled_regions,
    )
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing import find_matching_paren_for_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(raw_prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "name":
            continue

        match_end = match.end()
        if match.group(2) is not None:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                match_end = paren_end + 1

        rewritten = (
            f"{protected[: match.start()]}%name:{retry_name}{protected[match_end:]}"
        )
        rewritten = unprotect_disabled_regions(rewritten, disabled)
        return unprotect_fenced_blocks(rewritten, fenced)

    protected = f"%name:{retry_name}\n{protected}"
    protected = unprotect_disabled_regions(protected, disabled)
    return unprotect_fenced_blocks(protected, fenced)


class EntryPointsMixin:
    """Mixin providing agent start entry points."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    marked_indices: set[int]
    _agents: list[Agent]

    # State for prompt input
    _prompt_context: PromptContext | None = None
    # State for bulk agent runs
    _bulk_changespecs: list[ChangeSpec] | None = None
    # State for repeat-last-@/<space> selection
    _last_custom_agent_selection: SelectionItem | None = None

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

    def _start_prompt_history_from_last_selection(
        self, *, show_cancelled: bool = False
    ) -> None:
        """Show prompt history modal for the last agent selection (bound to ,.)."""
        from pathlib import Path

        from sase.core.time import generate_timestamp

        from ...modals import (
            PromptHistoryAction,
            PromptHistoryModal,
            PromptHistoryResult,
        )

        # Load last selection (same as <space>)
        last = self._last_custom_agent_selection
        if last is None:
            from sase.ace.last_agent_selection import load_last_agent_selection

            last = load_last_agent_selection()
            if last is not None:
                self._last_custom_agent_selection = last
        if last is None:
            self.notify("No previous @/<space> selection", severity="warning")  # type: ignore[attr-defined]
            return

        # Resolve VCS prefix
        project_name: str = last.project_name
        project_file = os.path.expanduser(
            f"~/.sase/projects/{project_name}/{project_name}.gp"
        )
        name = last.cl_name if last.item_type == "cl" and last.cl_name else project_name
        vcs_prefix = _vcs_prompt_prefix(project_file, name).rstrip()

        # Set up prompt context (same as _show_prompt_input_bar_for_home)
        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=os.path.expanduser("~/.sase/projects/home/home.gp"),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=name,
            display_name=name,
            update_target="",
            is_home_mode=True,
        )

        def _build_prompt(prompt_text: str) -> str:
            if vcs_prefix:
                from sase.xprompt import replace_vcs_workflow_tags

                return replace_vcs_workflow_tags(prompt_text, vcs_prefix)
            return prompt_text

        def on_history_select(result: PromptHistoryResult | None) -> None:
            if result is None:
                self._prompt_context = None
                return

            if result.action == PromptHistoryAction.SUBMIT:
                self._finish_agent_launch(_build_prompt(result.prompt_text))  # type: ignore[attr-defined]
            elif result.action == PromptHistoryAction.LOAD:
                # Mount prompt bar and load text into it
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=_build_prompt(result.prompt_text),
                    display_name=name,
                    history_sort_key=name,
                )
            else:
                # Edit in external editor
                prompt_for_editor = _build_prompt(result.prompt_text)
                edited_prompt = self._open_editor_for_agent_prompt(prompt_for_editor)  # type: ignore[attr-defined]
                if edited_prompt:
                    self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
                else:
                    self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
                    self._prompt_context = None

        self.push_screen(  # type: ignore[attr-defined]
            PromptHistoryModal(
                sort_by=self._prompt_context.history_sort_key,
                workspace=self._prompt_context.project_name,
                show_cancelled=show_cancelled,
            ),
            on_history_select,
        )

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

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agents available", severity="warning")  # type: ignore[attr-defined]
            return
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

    def _retry_edit_agent(self) -> None:
        """Show the selected agent's prompt in the prompt input bar for re-launch.

        Like :meth:`_kill_and_edit_agent` but without killing or dismissing
        the existing agent.  The user can press ``Ctrl+G`` to open their
        editor from the prompt input bar.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        raw_prompt = agent.get_raw_xprompt_content()

        if raw_prompt is None:
            self.notify("No prompt found for this agent", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.agent_name:
            try:
                from sase.agent.names import allocate_retry_name

                retry_name = allocate_retry_name(agent.agent_name)
                raw_prompt = _rewrite_retry_prompt_name(raw_prompt, retry_name)
            except Exception:
                self.notify(  # type: ignore[attr-defined]
                    "Could not allocate retry name; using original prompt",
                    severity="warning",
                )

        self._edit_and_relaunch_agent(
            raw_prompt, agent.project_file, agent.cl_name, agent.is_project_agent
        )

    def _kill_and_edit_agent(self) -> None:
        """Kill the selected agent, then show its prompt in the prompt input bar.

        Reads the agent's raw xprompt content, kills the agent (with
        confirmation if running), and shows the prompt in the prompt input
        bar for editing.  The user can press ``Ctrl+G`` to open their
        editor, or submit directly from the bar.
        """
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

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
            # No confirmation needed - dismiss and show prompt bar
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
        """Show agent prompt in the prompt input bar for editing and relaunch.

        The prompt is formatted with prettier before loading into the bar.
        The user can edit inline and submit, or press ``Ctrl+G`` to open
        their editor.

        Args:
            raw_prompt: The agent's raw xprompt content.
            project_file: The agent's project file path.
            cl_name: The agent's CL name.
            is_project_agent: Whether the agent was a project-level agent.
        """
        from pathlib import Path

        from sase.core.time import generate_timestamp

        from ...modals import SelectionItem
        from ...widgets import PromptInputBar

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

        # Remove any existing prompt bar before mounting a new one.
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

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

        # Format prompt with prettier for nice wrapping in the input bar
        try:
            screen_width = self.screen.size.width  # type: ignore[attr-defined]
        except Exception:
            screen_width = 80
        formatted_prompt = _format_prompt_with_prettier(raw_prompt, screen_width)

        # Show prompt input bar with the formatted prompt
        self.mount(  # type: ignore[attr-defined]
            PromptInputBar(initial_value=formatted_prompt, id="prompt-input-bar")
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
