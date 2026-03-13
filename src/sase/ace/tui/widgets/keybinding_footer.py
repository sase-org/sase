"""Keybinding footer widget for the ace TUI.

Footer Convention
-----------------
The footer displays only **entry-dependent** keymaps — bindings whose
availability is determined by a property of the currently selected entry
(ChangeSpec on CLs, Agent on Agents, Jack/BgCmd on AXE).

Rules:
  1. A keymap appears in the footer **if and only if** it has an associated
     condition based on the selected entry.
  2. There MUST exist an entry for which the keymap IS available and an entry
     for which it is NOT available (i.e. the condition is non-trivial).
  3. Global actions (quit, refresh, tab switch, fold, edit query, etc.) are
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

if TYPE_CHECKING:
    from ..models.agent import Agent


class KeybindingFooter(Horizontal):
    """Footer showing available keybindings with status indicator on the right."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the footer widget."""
        super().__init__(**kwargs)
        self._axe_running: bool = False
        self._axe_starting: bool = False
        self._axe_stopping: bool = False
        self._bgcmd_running_count: int = 0
        self._bgcmd_done_count: int = 0
        self._runner_count: int = 0

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

    def update_bindings(self, changespec: ChangeSpec) -> None:
        """Update bindings based on current ChangeSpec (entry-dependent only)."""
        bindings = self._compute_available_bindings(changespec)
        text = self._format_bindings(bindings)
        self._update_display(text)

    def show_empty(self) -> None:
        """Show empty state bindings."""
        text = Text()
        text.append("/", style="bold #00D7AF")
        text.append(" edit query", style="dim")
        self._update_display(text)

    def update_agent_bindings(self, agent: "Agent | None") -> None:
        """Update bindings for Agents tab (entry-dependent only)."""
        bindings = self._compute_agent_bindings(agent)
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
        "start/stop axe" (AxeParentItem) and "kill" (JackItem / BgCmdItem).
        """
        bindings: list[tuple[str, str]] = []
        if axe_current_view == "axe":
            label = "stop axe" if self._axe_running else "start axe"
        else:
            label = "kill"
        bindings.append(("x", label))
        return bindings

    def update_leader_bindings(self, *, current_tab: str = "changespecs") -> None:
        """Update bindings to show leader mode options.

        Args:
            current_tab: The currently active tab name.
        """
        bindings: list[tuple[str, str]] = []
        if current_tab == "changespecs":
            bindings.append(("!", "run cmd (CL)"))
            bindings.append(("m", "kill mentors"))
        if self._runner_count > 0:
            bindings.append(("r", f"runners ({self._runner_count})"))
        bindings.append(("h", "agent (home)"))
        if current_tab == "changespecs":
            bindings.append(("Space", "run agent (CL)"))
        elif current_tab == "agents":
            bindings.append(("Space", "run agent (CL)"))
        bindings.append(("Esc", "cancel"))
        text = self._format_bindings(bindings)
        # Add leader mode indicator prefix
        prefix = Text()
        prefix.append("LEADER ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_bang_bindings(self) -> None:
        """Update bindings to show bang mode options."""
        bindings = [
            ("!", "run cmd"),
            ("x", "start/stop axe"),
            ("Esc", "cancel"),
        ]
        text = self._format_bindings(bindings)
        # Add bang mode indicator prefix
        prefix = Text()
        prefix.append("BANG ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def update_copy_bindings(self, tab: str, *, file_visible: bool = False) -> None:
        """Update bindings to show copy mode options for the current tab.

        Args:
            tab: Current tab name ("changespecs", "agents", or "axe").
            file_visible: Whether the file panel is visible (agents tab only).
        """
        if tab == "changespecs":
            bindings = [
                ("%", "raw"),
                ("!", "+snap"),
                ("b", "bug"),
                ("c", "CL#"),
                ("n", "name"),
                ("p", "spec"),
                ("s", "snap"),
                ("Esc", "cancel"),
            ]
        elif tab == "agents":
            bindings = [
                ("c", "chat"),
                ("s", "snap"),
                ("Esc", "cancel"),
            ]
            if file_visible:
                bindings.insert(-1, ("E", "file path"))
        else:  # axe
            bindings = [
                ("o", "visible"),
                ("O", "full"),
                ("s", "snap"),
                ("Esc", "cancel"),
            ]
        text = self._format_bindings(bindings)
        prefix = Text()
        prefix.append("COPY ", style="bold #FFD700")
        prefix.append_text(text)
        self._update_display(prefix)

    def _compute_agent_bindings(
        self,
        agent: "Agent | None",
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for Agents tab.

        Only bindings whose availability depends on the selected agent's
        state are included (see module docstring for the full convention).
        """
        bindings: list[tuple[str, str]] = []

        if agent is None:
            return bindings

        # --- Status-dependent actions ---
        if agent.status in ("DONE", "FAILED"):
            bindings.append(("x", "dismiss"))
            if agent.status != "FAILED":
                bindings.append(("e", "edit chat"))
                if agent.response_path:
                    bindings.append(("r", "resume"))
        elif agent.status == "WAITING INPUT":
            bindings.append(("a", "answer"))
            if agent.pid is None:
                bindings.append(("x", "dismiss"))
            else:
                bindings.append(("x", "kill"))
        else:
            # RUNNING or other active statuses
            if agent.pid is None:
                bindings.append(("x", "dismiss"))
            else:
                bindings.append(("x", "kill"))
            if agent.status == "WAITING":
                bindings.append(("w", "unwait"))
            _APPROVE_ELIGIBLE = {
                "RUNNING",
                "PLANNING",
                "PLAN APPROVED",
                "WAITING",
                "QUESTION",
            }
            if agent.status in _APPROVE_ELIGIBLE:
                if not agent.approve:
                    bindings.append(("a", "approve"))
                else:
                    bindings.append(("a", "unapprove"))

        # Name agent (not available for done/failed agents)
        if agent.status not in ("DONE", "FAILED"):
            bindings.append(("n", "name"))

        # Jump to CL (only for ChangeSpec-level agents, not project-level)
        if not agent.is_project_agent:
            bindings.append(("<enter>", "go to CL"))

        return bindings

    def _compute_available_bindings(
        self,
        changespec: ChangeSpec,
    ) -> list[tuple[str, str]]:
        """Compute entry-dependent bindings for CLs tab.

        Only bindings whose availability depends on the selected ChangeSpec's
        state are included (see module docstring for the full convention).
        """
        bindings: list[tuple[str, str]] = []

        # Accept proposal (only if proposed entries exist)
        if changespec.commits and any(e.is_proposed for e in changespec.commits):
            bindings.append(("a", "accept"))

        # Diff (only if CL exists)
        if changespec.cl is not None:
            bindings.append(("d", "diff"))

        # Get base status for visibility checks
        from ...changespec import get_base_status

        base_status = get_base_status(changespec.status)

        # Reword (only if CL exists AND status is WIP, Draft, Ready, or Mailed)
        if changespec.cl is not None:
            if base_status in ("WIP", "Draft", "Ready", "Mailed"):
                bindings.append(("w", "reword"))

        # Mail (only if status is Ready)
        if base_status == "Ready":
            bindings.append(("M", "mail"))

        # Rebase (only if status is WIP, Draft, Ready, or Mailed)
        if base_status in ("WIP", "Draft", "Ready", "Mailed"):
            bindings.append(("b", "rebase"))

        # Rewind (only if status is not Submitted/Reverted and >=2 accepted entries)
        if base_status not in ("Submitted", "Reverted") and changespec.commits:
            numeric_entries = [e for e in changespec.commits if not e.is_proposed]
            if len(numeric_entries) >= 2:
                bindings.append(("R", "rewind"))

        # Sync (only if status is WIP, Draft, Ready, or Mailed)
        if base_status in ("WIP", "Draft", "Ready", "Mailed"):
            bindings.append(("Y", "sync"))

        # Rename (only if status is not Submitted or Reverted)
        if base_status not in ("Submitted", "Reverted"):
            bindings.append(("n", "rename"))

        # Hooks from failed targets (only if failed hooks file exists)
        if get_failed_hooks_file_path(changespec):
            bindings.append(("H", "hooks (failed)"))

        # Run workflows (only if workflows available for this ChangeSpec)
        workflows = get_available_workflows(changespec)
        if len(workflows) == 1:
            bindings.append(("r", f"run {workflows[0]}"))
        elif len(workflows) > 1:
            bindings.append(("r", f"run ({len(workflows)} workflows)"))

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
