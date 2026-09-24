"""``<enter>`` navigation from a Procs pane monitor row to its agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import OptionList

from ..proc_observer import ObservedProc, is_monitor_shell_row

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from ..models.agent import Agent
else:
    _MixinBase = object

MONITOR_AGENT_JUMP_HINT = "⏎: agent"
COMMAND_LINE_BLOCK_JUMP_HINT = "⏎: block"


def is_command_line_row(task: Any) -> bool:
    """Return whether a Procs row is a TUI Command Line proc."""
    from sase.procs.command_line import COMMAND_LINE_PROC_TAG

    return COMMAND_LINE_PROC_TAG in tuple(getattr(task, "tags", None) or ())


def _monitor_jump_agent(app: Any, proc_id: str) -> Agent | None:
    """Return the loaded Agent row whose ``monitor_id`` names this proc."""
    for agent in getattr(app, "_agents", ()):
        if getattr(agent, "monitor_id", None) == proc_id:
            return agent
    return None


class ProcsPaneAgentJumpMixin(_MixinBase):
    """Resolve a monitor row to its agent and reveal it on the Agents tab."""

    if TYPE_CHECKING:
        _monitor_agent_names: dict[str, str]

        def _get_selected_task(self) -> ObservedProc | None: ...

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Route <enter>/click on the task list to its row action."""
        event.stop()
        task = self._get_selected_task()
        if task is not None and is_command_line_row(task):
            self.action_open_command_line_block()
            return
        self.action_open_monitor_agent()

    def _monitor_jump_hint(self) -> str | None:
        """Return the conditional hints-line token for the selected row."""
        task = self._get_selected_task()
        if task is None or not is_monitor_shell_row(task):
            return None
        if _monitor_jump_agent(self.app, task.proc_id) is None:
            return None
        return MONITOR_AGENT_JUMP_HINT

    def _command_line_jump_hint(self) -> str | None:
        """Return the hints-line token for a selected Command Line row."""
        task = self._get_selected_task()
        if task is None or not is_command_line_row(task):
            return None
        return COMMAND_LINE_BLOCK_JUMP_HINT

    def action_open_command_line_block(self) -> None:
        """Open the Command Line focused on the selected command-line row."""
        if self.jump_mode_active:  # type: ignore[attr-defined]
            return
        task = self._get_selected_task()
        if task is None or not is_command_line_row(task):
            return
        proc_id = task.durable_proc_id or task.proc_id
        self._jump_to_command_line_block(proc_id)

    def _jump_to_command_line_block(self, proc_id: str) -> None:
        """Close the Admin Center, then open the Command Line on that block."""
        from .config_center_modal import ConfigCenterModal

        screen = self.screen  # type: ignore[attr-defined]
        if not isinstance(screen, ConfigCenterModal):
            return
        screen.action_close()

        app = self.app  # type: ignore[attr-defined]
        app.call_after_refresh(lambda: open_command_line_on_block(app, proc_id))

    def action_open_monitor_agent(self) -> None:
        """Dismiss the Admin Center and reveal the selected monitor's agent."""
        if self.jump_mode_active:  # type: ignore[attr-defined]
            return
        task = self._get_selected_task()
        if task is None or not is_monitor_shell_row(task):
            return

        agent = _monitor_jump_agent(self.app, task.proc_id)
        if agent is None:
            name = self._monitor_agent_names.get(task.proc_id)
            subject = f" for {name}" if name else ""
            self.notify(  # type: ignore[attr-defined]
                f"No agent row{subject} on the Agents tab", severity="warning"
            )
            return

        self._jump_to_monitor_agent(agent.identity)

    def _jump_to_monitor_agent(self, target_identity: Any) -> None:
        """Close the Admin Center, remembering Procs, then reveal the agent."""
        from .config_center_modal import ConfigCenterModal

        screen = self.screen  # type: ignore[attr-defined]
        if not isinstance(screen, ConfigCenterModal):
            return
        screen.action_close()

        app = self.app  # type: ignore[attr-defined]

        def _reveal() -> None:
            app._save_current_tab_position()  # type: ignore[attr-defined]
            app.current_tab = "agents"  # type: ignore[attr-defined]
            app._reveal_agent_row(  # type: ignore[attr-defined]
                target_identity, subject="Monitor agent"
            )

        app.call_after_refresh(_reveal)


def open_command_line_on_block(app: Any, proc_id: str) -> bool:
    """Ensure a transcript block for *proc_id* and open the panel on it.

    Adds the block when the transcript lacks it; a missing (pruned) record
    still opens the panel and reports the pruned record. Returns whether a
    block exists for *proc_id*.
    """
    from sase.ace.tui.command_line.restore import ensure_block_for_proc
    from sase.ace.tui.command_line.session import command_line_session_for

    session = command_line_session_for(app)
    try:
        block = ensure_block_for_proc(session, proc_id)
    except Exception:  # noqa: BLE001 - store reads are best effort.
        block = None
    session.focus_block_proc_id = proc_id
    opener = getattr(app, "action_open_command_line", None)
    if callable(opener):
        opener()
    if block is None:
        notify = getattr(app, "notify", None)
        if callable(notify):
            notify("Proc record pruned", severity="warning")
    return block is not None


__all__ = [
    "COMMAND_LINE_BLOCK_JUMP_HINT",
    "MONITOR_AGENT_JUMP_HINT",
    "ProcsPaneAgentJumpMixin",
    "is_command_line_row",
    "open_command_line_on_block",
]
