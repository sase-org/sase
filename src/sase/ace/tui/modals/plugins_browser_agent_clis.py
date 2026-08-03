"""Agent-CLI inventory and detail browser for the Admin Center Updates pane."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.agent_clis.models import (
    AgentCliStatus,
    AgentCliUpdateResult,
)
from sase.agent_clis.history import AgentCliUpdateRun

from .plugins_browser_agent_clis_actions import (
    AgentCliBrowserActionsMixin,
    agent_cli_result_line as agent_cli_result_line,
)
from .plugins_browser_agent_clis_config import (
    AgentCliHistoryConfig,
    load_agent_cli_history_config as load_agent_cli_history_config,
)
from .plugins_browser_constants import _SUBTAB_NAV_HINT
from .plugins_browser_agent_clis_history import build_agent_cli_history_panel

_ITEM_PREFIX = "agent-cli__"
_DETAIL_PLACEHOLDER = "Select an agent CLI to view its update details."
_ACCENT = "#87D7FF"


class AgentCliBrowserMixin(AgentCliBrowserActionsMixin):
    """Render the Agent CLIs browser and provide its update actions."""

    if TYPE_CHECKING:
        _agent_cli_colors: dict[str, str]
        _agent_cli_detail_name: str | None
        _agent_cli_error: str | None
        _agent_cli_history: tuple[AgentCliUpdateRun, ...]
        _agent_cli_history_config: AgentCliHistoryConfig
        _agent_cli_history_error: str | None
        _agent_cli_history_key: tuple[str | None, bool] | None
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _loading: bool
        _marked_agent_clis: set[str]
        _offline: bool
        _now: float
        _session_state: Any
        _agent_cli_selection_guard: ProgrammaticSelectionGuard
        _updates_loaded_once: bool

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

    # -- inventory rendering -------------------------------------------------

    def _render_agent_clis(self) -> None:
        """Refresh the Agent CLIs master/detail surface from loaded state."""
        option_list = self._agent_cli_option_list()
        preferred = (
            self._highlighted_agent_cli_name()
            or self._session_state.agent_clis.identity
        )
        selected_index: int | None = None
        if option_list is not None:
            self._agent_cli_selection_guard.clear()
            option_list.clear_options()
            for status in self._agent_cli_statuses:
                option_list.add_option(
                    Option(
                        self._agent_cli_row(status),
                        id=f"{_ITEM_PREFIX}{status.name}",
                    )
                )
            if self._agent_cli_statuses:
                selected_index = restore_selection_by_identity(
                    self._agent_cli_statuses,
                    prior_identity=preferred,
                    prior_visual_row=self._session_state.agent_clis.row,
                    identity_fn=lambda status: status.name,
                )
                identity = self._agent_cli_statuses[selected_index].name
                self._agent_cli_selection_guard.prepare(identity, selected_index)
                option_list.highlighted = selected_index
            else:
                option_list.highlighted = None
        self._record_agent_cli_bookmark(
            selected_index,
            authoritative=(self._updates_loaded_once and self._agent_cli_error is None),
        )
        self._prune_agent_cli_marks()
        self._update_static("#agent-clis-summary", self._agent_cli_summary())
        self._update_static("#agent-clis-status", self._agent_cli_status_message())
        self._update_static("#agent-clis-hints", self._agent_cli_hints())
        self._sync_agent_cli_visibility()
        self._render_agent_cli_detail(force=True)

    def _record_agent_cli_bookmark(
        self, index: int | None, *, authoritative: bool = True
    ) -> None:
        if index is None or not (0 <= index < len(self._agent_cli_statuses)):
            if authoritative and self._agent_cli_error is None:
                self._session_state.agent_clis.record(None, None)
            elif not authoritative:
                self._session_state.agent_clis.display(None, None)
            return
        status = self._agent_cli_statuses[index]
        if authoritative:
            self._session_state.agent_clis.record(status.name, index)
        else:
            self._session_state.agent_clis.display(status.name, index)

    def _agent_cli_row(self, status: AgentCliStatus) -> Text:
        text = Text()
        if status.name in self._marked_agent_clis:
            text.append("[✓] ", style="bold #00D700")
        else:
            text.append("    ")
        glyph = "●" if status.installed else "○"
        text.append(glyph, style="green" if status.installed else "dim")
        text.append(" ")
        text.append(
            status.display_name,
            style=f"bold {self._agent_cli_color(status)}",
        )
        version = self._agent_cli_version_label(status)
        if version:
            text.append("  ")
            text.append(version, style="dim")
        text.append("  ")
        text.append(self._install_method_label(status), style="bold dim")
        if status.update_available:
            text.append("  ↑", style="bold cyan")
        return text

    @staticmethod
    def _agent_cli_version_label(status: AgentCliStatus) -> str:
        installed = status.installed_version
        latest = status.latest_version
        if installed and latest and status.update_available:
            return f"v{installed} → v{latest}"
        if installed:
            return f"v{installed}"
        if status.installed:
            return "version unknown"
        return "not installed"

    @staticmethod
    def _install_method_label(status: AgentCliStatus) -> str:
        return f"[{status.install_method.value.replace('_', ' ')}]"

    def _agent_cli_color(self, status: AgentCliStatus) -> str:
        return self._agent_cli_colors.get(status.name, _ACCENT)

    def _agent_cli_summary(self) -> Text:
        if self._loading and not self._agent_cli_statuses:
            line = "Agent CLIs · loading…"
        elif self._agent_cli_error is not None and not self._agent_cli_statuses:
            line = "Agent CLIs · unavailable"
        else:
            installed = sum(status.installed for status in self._agent_cli_statuses)
            updates = sum(
                status.update_available for status in self._agent_cli_statuses
            )
            line = (
                f"{len(self._agent_cli_statuses)} agent CLIs · {installed} installed · "
                f"{updates} updates available"
            )
        text = Text(line, style="bold")
        if self._offline:
            text.append("   ")
            text.append("⚠ OFFLINE", style="bold yellow")
        return text

    def _agent_cli_status_message(self) -> str:
        if self._loading and not self._agent_cli_statuses:
            return "Loading agent CLIs…"
        if self._agent_cli_error is not None:
            return f"Could not load agent CLIs:\n{self._agent_cli_error}"
        if not self._agent_cli_statuses:
            return "No registered agent CLIs were found."
        return ""

    def _sync_agent_cli_visibility(self) -> None:
        try:
            status = self.query_one("#agent-clis-status", Static)  # type: ignore[attr-defined]
            option_list = self.query_one("#agent-clis-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        show_status = self._agent_cli_error is not None or not self._agent_cli_statuses
        status.display = show_status
        option_list.display = not show_status

    def _agent_cli_hints(self) -> str:
        offline = " (on)" if self._offline else " off"
        parts: list[str] = []
        mark_count = len(self._marked_agent_clis)
        if self._can_mark_agent_cli(self._current_agent_cli()):
            parts.append("space mark")
        parts.extend(
            [
                "A update",
                "u core+plugins",
                "a sync agents",
                "r reload",
                "ctrl+d/u scroll",
                f"o{offline}",
                _SUBTAB_NAV_HINT,
            ]
        )
        if mark_count:
            parts.extend((f"{mark_count} marked", "esc clear"))
        else:
            parts.append("esc")
        return " · ".join(parts)

    # -- selection + detail --------------------------------------------------

    def _agent_cli_option_list(self) -> OptionList | None:
        try:
            return self.query_one("#agent-clis-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _current_agent_cli(self) -> AgentCliStatus | None:
        option_list = self._agent_cli_option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        if not option.id:
            return None
        return self._agent_cli_by_name(str(option.id).removeprefix(_ITEM_PREFIX))

    def _agent_cli_by_name(self, name: str) -> AgentCliStatus | None:
        return next(
            (status for status in self._agent_cli_statuses if status.name == name),
            None,
        )

    def _highlighted_agent_cli_name(self) -> str | None:
        status = self._current_agent_cli()
        return status.name if status is not None else None

    @staticmethod
    def _highlight_agent_cli(option_list: OptionList, name: str) -> bool:
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == target:
                option_list.highlighted = index
                return True
        return False

    def _on_agent_cli_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option is None or event.option.id is None:
            return
        option_list = self._agent_cli_option_list()
        highlighted = option_list.highlighted if option_list is not None else None
        if highlighted is None or not (
            0 <= highlighted < len(self._agent_cli_statuses)
        ):
            return
        identity = str(event.option.id).removeprefix(_ITEM_PREFIX)
        current_identity = self._agent_cli_statuses[highlighted].name
        if (
            identity != current_identity
            or self._agent_cli_selection_guard.should_ignore(
                identity,
                highlighted,
                current_identity=current_identity,
                current_row=highlighted,
            )
        ):
            return
        self._record_agent_cli_bookmark(highlighted)
        self._update_static("#agent-clis-hints", self._agent_cli_hints())
        debouncer = getattr(self, "_detail_debouncer", None)
        if debouncer is None:
            self._render_agent_cli_detail()
        else:
            debouncer.schedule(self._render_agent_cli_detail)

    def _render_agent_cli_detail(self, *, force: bool = False) -> None:
        status = self._current_agent_cli()
        name = status.name if status is not None else None
        if not force and name == self._agent_cli_detail_name:
            self._render_agent_cli_history()
            return
        self._agent_cli_detail_name = name
        try:
            detail = self.query_one("#agent-clis-detail", Static)  # type: ignore[attr-defined]
        except Exception:
            pass
        else:
            detail.update(
                _DETAIL_PLACEHOLDER
                if status is None
                else self._agent_cli_detail_panel(status)
            )
        self._render_agent_cli_history(force=force)

    def _render_agent_cli_history(self, *, force: bool = False) -> None:
        status = self._current_agent_cli()
        scope = bool(self._session_state.agent_cli_history_all)
        key = (status.name if status is not None else None, scope)
        if not force and key == self._agent_cli_history_key:
            return
        self._agent_cli_history_key = key
        try:
            history = self.query_one("#agent-clis-history", Static)  # type: ignore[attr-defined]
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
