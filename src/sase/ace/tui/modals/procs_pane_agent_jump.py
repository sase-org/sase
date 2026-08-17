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
        """Route <enter>/click on the task list to the agent-jump action."""
        event.stop()
        self.action_open_monitor_agent()

    def _monitor_jump_hint(self) -> str | None:
        """Return the conditional hints-line token for the selected row."""
        task = self._get_selected_task()
        if task is None or not is_monitor_shell_row(task):
            return None
        if _monitor_jump_agent(self.app, task.proc_id) is None:
            return None
        return MONITOR_AGENT_JUMP_HINT

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


__all__ = ["MONITOR_AGENT_JUMP_HINT", "ProcsPaneAgentJumpMixin"]
