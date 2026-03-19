"""Keybinding footer widget for the ace TUI.

Footer Convention
-----------------
The footer displays **conditional** keymaps — bindings whose availability
is determined by the currently selected entry (ChangeSpec, Agent, etc.) or
by transient app state (e.g. marks exist, completed agents present).

Rules:
  1. A keymap appears in the footer **if and only if** it has an associated
     condition that is sometimes true and sometimes false.
  2. Global actions (quit, refresh, tab switch, fold, edit query, etc.) are
     NOT shown — they belong in the help modal only.

Formatting:
  - Keymaps are sorted alphabetically; symbol keys (``<enter>``, ``<space>``,
    ``.``, ``/``, …) come first.
  - Named keys are rendered in angle brackets and lowercased:
    ``<enter>``, ``<space>``.
"""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from ...changespec import ChangeSpec
from ...hooks import get_failed_hooks_file_path
from ...operations import get_available_workflows
from ..keymaps import KeymapRegistry, footer_key_display, load_keymap_registry

if TYPE_CHECKING:
    from ..models.agent import Agent


class KeybindingFooter(Horizontal):
    """Footer showing available keybindings with status indicator on the right."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the footer widget."""
        super().__init__(**kwargs)
        self._registry = load_keymap_registry({})
        self._axe_running: bool = False
        self._axe_starting: bool = False
        self._axe_stopping: bool = False
        self._bgcmd_running_count: int = 0
        self._bgcmd_done_count: int = 0
        self._runner_count: int = 0

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry with user config."""
        self._registry = registry

    def _kd(self, action_name: str) -> str:
        """Get footer display key for an app-level action."""
        return footer_key_display(getattr(self._registry.app, action_name))

    def compose(self) -> ComposeResult:
        """Compose the footer with bindings on left and status on right."""
        yield Static(id="keybinding-content")
        yield Static(id="keybinding-status")

    def set_axe_running(self, running: bool) -> None:
        """Update the axe running state for binding labels.

        Args:
            running: Whether axe daemon is currently running.
        """
        self._axe_running = running
        self._update_status()

    def set_axe_starting(self, starting: bool) -> None:
        """Update the axe starting state.

        Args:
            starting: Whether axe daemon is currently starting.
        """
        self._axe_starting = starting
        self._update_status()

    def set_axe_stopping(self, stopping: bool) -> None:
        """Update the axe stopping state.

        Args:
            stopping: Whether axe daemon is currently stopping.
        """
        self._axe_stopping = stopping
        self._update_status()

    def set_bgcmd_count(self, running_count: int, done_count: int) -> None:
        """Update the background command counts.

        Args:
            running_count: Number of running background commands.
            done_count: Number of done (completed) background commands.
        """
        self._bgcmd_running_count = running_count
        self._bgcmd_done_count = done_count
        self._update_status()

    def set_runner_count(self, count: int) -> None:
        """Update the runner count for AXE tab bindings.

        Args:
            count: Number of active runners (processes + agents).
        """
        self._runner_count = count

    def _update_status(self) -> None:
        """Update the status indicator widget."""
        try:
            status = self.query_one("#keybinding-status", Static)
            status.update(self._get_status_text())
        except Exception:
            pass

    def _get_status_text(self) -> Text:
        """Get styled status indicator text.

        Returns:
            Formatted Text object for the status indicator.
        """
        text = Text()
        if self._axe_starting:
            text.append(" STARTING ", style="bold black on rgb(255,255,0)")
        elif self._axe_stopping:
            text.append(" STOPPING ", style="bold black on rgb(255,165,0)")
        elif self._axe_running:
            text.append(" RUNNING ", style="bold black on green")
        else:
            text.append(" STOPPED ", style="bold white on red")

        # Add bgcmd badges if there are any background commands
        if self._bgcmd_running_count > 0 or self._bgcmd_done_count > 0:
            text.append(" ")
            # Running count badge: [*R] in cyan
            if self._bgcmd_running_count > 0:
                text.append(
                    f" [*{self._bgcmd_running_count}] ", style="bold black on #00D7AF"
                )
            # Done count badge: [✓D] in gold
            if self._bgcmd_done_count > 0:
                text.append(
                    f" [✓{self._bgcmd_done_count}] ", style="bold black on #FFD700"
                )

        return text

    def _update_display(self, bindings_text: Text) -> None:
        """Update both the bindings content and status indicator.

        Args:
            bindings_text: Formatted text for the keybindings.
        """
        try:
            content = self.query_one("#keybinding-content", Static)
            status = self.query_one("#keybinding-status", Static)
            content.update(bindings_text)
            status.update(self._get_status_text())
        except Exception:
            pass

    def update_bindings(self, changespec: ChangeSpec, *, mark_count: int = 0) -> None:
        """Update bindings based on current ChangeSpec and app state."""
        bindings = self._compute_available_bindings(changespec, mark_count=mark_count)
        text = self._format_bindings(bindings)
        self._update_display(text)

    def show_empty(self) -> None:
        """Show empty state bindings."""
        text = Text()
        text.append(self._kd("edit_query"), style="bold #00D7AF")
        text.append(" edit query", style="dim")
        self._update_display(text)

    def update_agent_bindings(
        self, agent: "Agent | None", *, completed_count: int = 0
    ) -> None:
        """Update bindings for Agents tab."""
        bindings = self._compute_agent_bindings(agent, completed_count=completed_count)
        text = self._format_bindings(bindings)
        self._update_display(text)

    def update_axe_bindings(self, *, axe_current_view: str | int = "axe") -> None:
        """Update bindings for Axe tab (entry-dependent only)."""
        bindings = self._compute_axe_bindings(axe_current_view)
        text = self._format_bindings(bindings)
        self._update_display(text)

    def _compute_axe_bindings(
        self,
        axe_current_view: str | int,
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for Axe tab.

        Only ``x`` is entry-dependent: its label changes between
        "start/stop axe" (AxeParentItem) and "kill" (LumberjackItem / BgCmdItem).
        """
        bindings: list[tuple[str, str]] = []
        if axe_current_view == "axe":
            label = "stop axe" if self._axe_running else "start axe"
        else:
            label = "kill"
        bindings.append((self._kd("kill_agent"), label))
        return bindings

    def update_fold_bindings(self) -> None:
        """Update bindings to show fold mode options."""
        d = footer_key_display
        keys = self._registry.fold_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("cycle_commits"), "commits"),
            (k("cycle_hooks"), "hooks"),
            (k("cycle_mentors"), "mentors"),
            (k("cycle_all"), "all"),
        ]
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("FOLD ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_leader_bindings(
        self,
        *,
        current_tab: str = "changespecs",
        has_comments: bool = False,
        has_notification: bool = False,
    ) -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
            has_comments: Whether the selected ChangeSpec has a COMMENTS field.
            has_notification: Whether the selected agent has a pending notification.
        """
        d = footer_key_display
        keys = self._registry.leader_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings: list[tuple[str, str]] = []
        if current_tab == "changespecs":
            if has_comments:
                bindings.append((k("clear_comments"), "clear comments"))
            bindings.append((k("run_cmd"), "run cmd (CL)"))
            bindings.append((k("kill_mentors"), "kill mentors"))
        if self._runner_count > 0:
            bindings.append((k("runners"), f"runners ({self._runner_count})"))
        bindings.append((k("agent_home"), "agent (home)"))
        if current_tab in ("changespecs", "agents"):
            bindings.append((k("agent_from_cl"), "run agent (CL)"))
        bindings.append((k("prompt_history"), "prompt history"))
        if current_tab == "agents":
            bindings.append((k("kill_and_edit"), "kill & edit"))
            if has_notification:
                bindings.append((k("jump_to_notification"), "notification"))
        bindings.append((k("activity_info"), "activity"))
        text = self._format_bindings(bindings)
        # Add leader mode indicator prefix
        prefix = Text()
        prefix.append("LEADER ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_bang_bindings(self) -> None:
        """Update bindings to show bang mode options."""
        d = footer_key_display
        keys = self._registry.bang_mode.keys

        def k(name: str) -> str:
            v = keys[name]
            assert isinstance(v, str)
            return d(v)

        bindings = [
            (k("run_cmd"), "run cmd"),
            (k("toggle_axe"), "start/stop axe"),
        ]
        text = self._format_bindings(bindings)
        # Add bang mode indicator prefix
        prefix = Text()
        prefix.append("BANG ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_custom_mode_bindings(self, mode_name: str) -> None:
        """Update bindings to show custom mode options.

        Args:
            mode_name: Name of the active custom mode.
        """
        d = footer_key_display
        mode = self._registry.modes.get(mode_name)
        if mode is None:
            return

        bindings: list[tuple[str, str]] = []
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            key = spec.get("key", "")
            desc = spec.get("description", action_name)
            bindings.append((d(key), desc))

        text = self._format_bindings(bindings)
        prefix = Text()
        display_name = mode_name.upper().replace("_", " ")
        prefix.append(f"{display_name} ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_copy_bindings(self, tab: str, *, file_visible: bool = False) -> None:
        """Update bindings to show copy mode options for the current tab.

        Args:
            tab: Current tab name ("changespecs", "agents", or "axe").
            file_visible: Whether the file panel is visible (agents tab only).
        """
        d = footer_key_display
        tab_keys = self._registry.copy_mode.keys.get(tab, {})
        assert isinstance(tab_keys, dict)

        def k(name: str) -> str:
            v = tab_keys[name]
            assert isinstance(v, str)
            return d(v)

        if tab == "changespecs":
            bindings = [
                (k("raw"), "raw"),
                (k("with_snapshot"), "+snap"),
                (k("bug"), "bug"),
                (k("cl_number"), "CL#"),
                (k("name"), "name"),
                (k("spec"), "spec"),
                (k("snapshot"), "snap"),
            ]
        elif tab == "agents":
            bindings = [
                (k("chat"), "chat"),
                (k("prompt"), "prompt"),
                (k("snapshot"), "snap"),
            ]
            if file_visible:
                bindings.append((k("file_path"), "file path"))
        else:  # axe
            bindings = [
                (k("visible"), "visible"),
                (k("full"), "full"),
                (k("snapshot"), "snap"),
            ]
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("COPY ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def _compute_agent_bindings(
        self,
        agent: "Agent | None",
        *,
        completed_count: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for Agents tab.

        Includes entry-dependent bindings (based on the selected agent's
        state) and app-state bindings (e.g. completed agents exist).
        """
        bindings: list[tuple[str, str]] = []

        if agent is None:
            # Even with no selected agent, show app-state bindings
            if completed_count > 0:
                bindings.append(
                    (
                        self._kd("toggle_axe"),
                        f"dismiss all ({completed_count})",
                    )
                )
            return bindings

        x = self._kd("kill_agent")

        # --- Status-dependent actions ---
        if agent.status in ("DONE", "FAILED"):
            bindings.append((x, "dismiss"))
            if agent.status != "FAILED":
                bindings.append((self._kd("edit_spec"), "edit chat"))
                if agent.response_path:
                    bindings.append((self._kd("run_workflow"), "resume"))
        elif agent.status == "WAITING INPUT":
            bindings.append((self._kd("accept_proposal"), "answer"))
            if agent.pid is None:
                bindings.append((x, "dismiss"))
            else:
                bindings.append((x, "kill"))
        else:
            # RUNNING or other active statuses
            if agent.pid is None:
                bindings.append((x, "dismiss"))
            else:
                bindings.append((x, "kill"))
            if agent.status == "WAITING":
                bindings.append((self._kd("reword"), "unwait"))
            _APPROVE_ELIGIBLE = {
                "RUNNING",
                "PLANNING",
                "PLAN APPROVED",
                "WAITING",
                "QUESTION",
            }
            if agent.status in _APPROVE_ELIGIBLE:
                if not agent.approve:
                    bindings.append((self._kd("accept_proposal"), "approve"))
                else:
                    bindings.append((self._kd("accept_proposal"), "unapprove"))

        # Send message to running agent (not done/failed)
        _INTERRUPTABLE = {
            "RUNNING",
            "PLAN APPROVED",
            "PLANNING",
            "WAITING",
            "QUESTION",
        }
        if agent.status in _INTERRUPTABLE:
            bindings.append((self._kd("toggle_mark"), "message"))

        # Name agent (not available for done/failed agents)
        if agent.status not in ("DONE", "FAILED"):
            bindings.append((self._kd("rename_cl"), "name"))

        # Open tmux window (only if agent has a workspace)
        if agent.workspace_num is not None and agent.workspace_num > 0:
            bindings.append((self._kd("start_tmux_mode"), "tmux"))

        # Jump to CL (for ChangeSpec-level agents, or project agents with meta CL/PR)
        if not agent.is_project_agent:
            bindings.append((self._kd("jump_to_agent_changespec"), "go to CL"))
        elif (
            agent.step_output
            and isinstance(agent.step_output, dict)
            and (
                agent.step_output.get("meta_new_cl")
                or agent.step_output.get("meta_new_pr")
            )
        ):
            bindings.append((self._kd("jump_to_agent_changespec"), "go to CL"))

        # --- App-state bindings ---

        # Dismiss all completed (only when completed agents exist)
        if completed_count > 0:
            bindings.append(
                (self._kd("toggle_axe"), f"dismiss all ({completed_count})")
            )

        return bindings

    def _compute_available_bindings(
        self,
        changespec: ChangeSpec,
        *,
        mark_count: int = 0,
    ) -> list[tuple[str, str]]:
        """Compute conditional bindings for CLs tab.

        Includes entry-dependent bindings (based on the selected ChangeSpec)
        and app-state bindings (e.g. marks exist).
        """
        bindings: list[tuple[str, str]] = []

        # Accept proposal (only if proposed entries exist)
        if changespec.commits and any(e.is_proposed for e in changespec.commits):
            bindings.append((self._kd("accept_proposal"), "accept"))

        # Diff (only if CL exists)
        if changespec.cl is not None:
            bindings.append((self._kd("show_diff"), "diff"))

        # Get base status for visibility checks
        from ...changespec import get_base_status

        base_status = get_base_status(changespec.status)

        _EDITABLE = ("WIP", "Draft", "Ready", "Mailed")

        # Reword (only if CL exists AND status is editable)
        if changespec.cl is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("reword"), "reword"))

        # Add tag (only if CL exists AND status is editable)
        if changespec.cl is not None:
            if base_status in _EDITABLE:
                bindings.append((self._kd("add_tag"), "add tag"))

        # Mail (only if status is Ready)
        if base_status == "Ready":
            bindings.append((self._kd("mail"), "mail"))

        # Rebase (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("rebase"), "rebase"))

        # Rewind (only if status is not Submitted/Reverted and >=2 accepted entries)
        if base_status not in ("Submitted", "Reverted") and changespec.commits:
            numeric_entries = [e for e in changespec.commits if not e.is_proposed]
            if len(numeric_entries) >= 2:
                bindings.append((self._kd("start_rewind"), "rewind"))

        # Sync (only if status is editable)
        if base_status in _EDITABLE:
            bindings.append((self._kd("sync"), "sync"))

        # Rename (only if status is not Submitted or Reverted)
        if base_status not in ("Submitted", "Reverted"):
            bindings.append((self._kd("rename_cl"), "rename"))

        # View files (only if CL exists)
        if changespec.cl is not None:
            bindings.append((self._kd("view_files"), "files"))

        # Hooks from failed targets (only if failed hooks file exists)
        if get_failed_hooks_file_path(changespec):
            bindings.append((self._kd("hooks_or_collapse_all"), "hooks (failed)"))

        # Run workflows (only if workflows available for this ChangeSpec)
        workflows = get_available_workflows(changespec)
        if len(workflows) == 1:
            bindings.append((self._kd("run_workflow"), f"run {workflows[0]}"))
        elif len(workflows) > 1:
            bindings.append(
                (self._kd("run_workflow"), f"run ({len(workflows)} workflows)")
            )

        # --- App-state bindings ---

        # Marks (only when marks exist)
        if mark_count > 0:
            bindings.append(
                (self._kd("bulk_change_status"), f"bulk status ({mark_count})")
            )
            bindings.append((self._kd("clear_marks"), f"unmark ({mark_count})"))

        return bindings

    def _format_bindings(self, bindings: list[tuple[str, str]]) -> Text:
        """Format bindings for display.

        Sorting: symbols first (angle-bracket keys like ``<enter>`` and
        non-alpha chars like ``.``), then alphabetical (case-insensitive,
        lowercase before uppercase for the same letter).
        """
        text = Text()

        def _is_symbol(key: str) -> bool:
            return key.startswith("<") or (len(key) == 1 and not key[0].isalpha())

        sorted_bindings = sorted(
            bindings,
            key=lambda x: (
                0 if _is_symbol(x[0]) else 1,
                x[0].strip("<>").lower(),
                0 if x[0][0].islower() or x[0].startswith("<") else 1,
                x[0],
            ),
        )

        for i, (key, label) in enumerate(sorted_bindings):
            if i > 0:
                text.append("  ")

            # Key in bold cyan
            text.append(key, style="bold #00D7AF")
            text.append(" ", style="")
            # Label in dim
            text.append(label, style="dim")

        return text
