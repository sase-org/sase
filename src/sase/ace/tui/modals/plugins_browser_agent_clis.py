"""Agent-CLI inventory and detail browser for the Admin Center Updates pane."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static

from sase.agent_clis.history import AgentCliUpdateRun
from sase.agent_clis.install import (
    AgentCliInstallOption,
    describe_agent_cli_install,
)
from sase.agent_clis.models import (
    AgentCliOperation,
    AgentCliStatus,
    AgentCliUpdateResult,
    InstallRoute,
    UpdateResultStatus,
)

from .plugins_browser_agent_clis_actions import (
    AgentCliBrowserActionsMixin,
    agent_cli_result_line as agent_cli_result_line,
)
from .plugins_browser_agent_clis_config import (
    AgentCliHistoryConfig,
    load_agent_cli_history_config as load_agent_cli_history_config,
)
from .plugins_browser_agent_clis_history import build_agent_cli_history_panel
from .plugins_browser_rows import UpdateRow

_ACCENT = "#87D7FF"


class AgentCliBrowserMixin(AgentCliBrowserActionsMixin):
    """Render agent-CLI detail/history and provide update actions."""

    if TYPE_CHECKING:
        _agent_cli_colors: dict[str, str]
        _agent_cli_history: tuple[AgentCliUpdateRun, ...]
        _agent_cli_history_config: AgentCliHistoryConfig
        _agent_cli_history_error: str | None
        _agent_cli_history_key: tuple[str | None, bool] | None
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _now: float
        _session_state: Any

        def _highlighted_row(self) -> UpdateRow | None: ...

    def _agent_cli_color(self, status: AgentCliStatus) -> str:
        return self._agent_cli_colors.get(status.name, _ACCENT)

    def _current_agent_cli(self) -> AgentCliStatus | None:
        row = self._highlighted_row()
        if row is None or row.kind != "agent-cli":
            return None
        payload = row.payload
        return payload if isinstance(payload, AgentCliStatus) else None

    def _agent_cli_by_name(self, name: str) -> AgentCliStatus | None:
        return next(
            (status for status in self._agent_cli_statuses if status.name == name),
            None,
        )

    def _render_agent_cli_history(self, *, force: bool = False) -> None:
        status = self._current_agent_cli()
        scope = bool(self._session_state.agent_cli_history_all)
        key = (status.name if status is not None else None, scope)
        if not force and key == self._agent_cli_history_key:
            return
        self._agent_cli_history_key = key
        try:
            history = self.query_one("#updates-history", Static)  # type: ignore[attr-defined]
        except Exception:
            return
        history.update(
            build_agent_cli_history_panel(
                status,
                self._agent_cli_history,
                enabled=self._agent_cli_history_config.enabled,
                error=self._agent_cli_history_error,
                all_clis=scope,
                now=self._now,
                max_rows=self._agent_cli_history_config.max_rows,
                colors=self._agent_cli_colors,
            )
        )

    def action_toggle_history_scope(self) -> None:
        """Toggle between the selected-CLI and all-CLIs history views."""
        self._session_state.agent_cli_history_all = not bool(
            self._session_state.agent_cli_history_all
        )
        self._render_agent_cli_history(force=True)

    def _agent_cli_detail_panel(self, status: AgentCliStatus) -> Panel:
        if not status.installed:
            return self._agent_cli_install_panel(status)
        entry = self._agent_cli_update_entry(status)
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        table.add_row("Provider", status.name)
        table.add_row("Binary", status.binary)
        table.add_row("Installed", status.installed_version or "not installed")
        table.add_row("Latest", status.latest_version or "unknown")
        table.add_row("Executable", status.executable or "not resolved")
        table.add_row("Install method", status.install_method.value.replace("_", " "))
        if entry.argv:
            table.add_row("Update command", shlex.join(entry.argv))
        elif entry.manual_argv:
            table.add_row("Manual command", shlex.join(entry.manual_argv))
        else:
            table.add_row("Update command", "none")
        if entry.skip_reason:
            table.add_row("Update status", entry.skip_reason)
        if status.docs_url:
            table.add_row("Documentation", status.docs_url)
        if status.version_error:
            table.add_row("Version probe", status.version_error)
        if status.latest_error:
            table.add_row("Latest probe", status.latest_error)
        outcome = self._agent_cli_results.get(status.name)
        if outcome is not None:
            table.add_row("Last outcome", agent_cli_result_line(outcome))
        return Panel(
            Group(table),
            title=status.display_name,
            border_style=self._agent_cli_color(status),
        )

    def _agent_cli_install_panel(self, status: AgentCliStatus) -> Panel:
        """Detail panel for a missing CLI: route, target, and call to action.

        Pure: the install option is I/O-free and results come from memory, so
        this never stats or probes on a render path.
        """
        option = describe_agent_cli_install(status)
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        table.add_row("Provider", status.name)
        table.add_row("Binary", status.binary)
        table.add_row("Status", "not installed")
        table.add_row("Latest", status.latest_version or "unknown")
        if option.route is InstallRoute.NPM:
            table.add_row("Install via", f"npm · {option.source}")
            table.add_row("Install command", option.command_hint)
        elif option.route is InstallRoute.SCRIPT:
            table.add_row("Install via", "install script")
            table.add_row("Script", option.source or "unknown")
            table.add_row(
                "Runs", "bash <downloaded script> — SHA-256 shown before it runs"
            )
            table.add_row("Target", _declared_install_target(status))
        else:
            if option.command_hint:
                table.add_row("How to install", option.command_hint)
        if status.docs_url:
            table.add_row("Documentation", status.docs_url)
        outcome = self._agent_cli_results.get(status.name)
        if outcome is not None:
            table.add_row("Last outcome", agent_cli_result_line(outcome))
        parts: list[RenderableType] = [table]
        call_to_action: Text | None = self._agent_cli_install_call_to_action(
            status, option
        )
        if call_to_action is not None:
            parts.append(Text(""))
            parts.append(call_to_action)
        return Panel(
            Group(*parts),
            title=f"{status.display_name} · not installed",
            border_style=self._agent_cli_color(status),
        )

    def _agent_cli_install_call_to_action(
        self, status: AgentCliStatus, option: AgentCliInstallOption
    ) -> Text | None:
        """The install/manual/off-PATH call to action for a missing CLI."""
        if not option.installable:
            note = Text(
                "○ SASE can't run this installer — follow the documentation above",
                style="yellow",
            )
            return note
        outcome = self._agent_cli_results.get(status.name)
        if (
            outcome is not None
            and outcome.operation is AgentCliOperation.INSTALL
            and outcome.status is UpdateResultStatus.UPDATED
            and outcome.install_dir_on_path is False
        ):
            location = outcome.install_dir or _declared_install_target(status)
            note = Text(
                f"⚠ Installed to {location}, which is not on PATH — add "
                f'export PATH="{location}:$PATH" to your shell startup file, '
                "then restart sase",
                style="yellow",
            )
            return note
        action = Text()
        action.append("↓ i install now", style="bold")
        action.append(" · Space mark for a bulk install", style="dim")
        return action


def _declared_install_target(status: AgentCliStatus) -> str:
    """The declared script-install target, with an env-override note."""
    target = status.install_dir or "unknown"
    if status.install_dir_env:
        return f"{target} ({status.install_dir_env} overrides)"
    return target
