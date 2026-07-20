"""Agent-CLI browser and update actions for the Admin Center Updates pane."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any, Literal

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
)
from sase.agent_clis.runner import CommandResult, run_command

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

_ITEM_PREFIX = "agent-cli__"
_DETAIL_PLACEHOLDER = "Select an agent CLI to view its update details."
_ACCENT = "#87D7FF"


class AgentCliBrowserMixin:
    """Render, mark, plan, confirm, and execute agent-CLI updates."""

    if TYPE_CHECKING:
        _active_subtab: str
        _agent_cli_colors: dict[str, str]
        _agent_cli_detail_name: str | None
        _agent_cli_error: str | None
        _agent_cli_plan_worker: Worker[Any] | None
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _loading: bool
        _marked_agent_clis: set[str]
        _marked_install: set[str]
        _offline: bool
        app: App[Any]
        is_mounted: bool

        def _clear_install_marks(self) -> None: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

    # -- inventory rendering -------------------------------------------------

    def _render_agent_clis(self) -> None:
        """Refresh the Agent CLIs master/detail surface from loaded state."""
        option_list = self._agent_cli_option_list()
        preferred = self._highlighted_agent_cli_name()
        if option_list is not None:
            option_list.clear_options()
            for status in self._agent_cli_statuses:
                option_list.add_option(
                    Option(
                        self._agent_cli_row(status),
                        id=f"{_ITEM_PREFIX}{status.name}",
                    )
                )
            if preferred is not None:
                self._highlight_agent_cli(option_list, preferred)
            if option_list.highlighted is None and option_list.option_count:
                option_list.highlighted = 0
        self._prune_agent_cli_marks()
        self._update_static("#agent-clis-summary", self._agent_cli_summary())
        self._update_static("#agent-clis-status", self._agent_cli_status_message())
        self._update_static("#agent-clis-hints", self._agent_cli_hints())
        self._sync_agent_cli_visibility()
        self._render_agent_cli_detail(force=True)

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
                "r reload",
                "ctrl+d/u scroll",
                f"o{offline}",
                "]/[ sub-tab",
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

    def _on_agent_cli_highlighted(self) -> None:
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
            return
        self._agent_cli_detail_name = name
        try:
            detail = self.query_one("#agent-clis-detail", Static)  # type: ignore[attr-defined]
        except Exception:
            return
        detail.update(
            _DETAIL_PLACEHOLDER
            if status is None
            else self._agent_cli_detail_panel(status)
        )

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
            table.add_row("Last outcome", _agent_cli_result_line(outcome))
        return Panel(
            Group(table),
            title=status.display_name,
            border_style=self._agent_cli_color(status),
        )

    # -- mark handling -------------------------------------------------------

    def action_toggle_mark(self) -> None:
        """Toggle the active Plugins or Agent CLIs mark."""
        if self._active_subtab == "plugins":
            self.action_toggle_install_mark()  # type: ignore[attr-defined]
        elif self._active_subtab == "agent-clis":
            self._toggle_agent_cli_mark()

    def _toggle_agent_cli_mark(self) -> None:
        if self._loading or self._agent_cli_plan_worker is not None:
            return
        status = self._current_agent_cli()
        if not self._can_mark_agent_cli(status):
            self._notify("Select an updatable agent CLI to mark.", severity="warning")
            return
        assert status is not None
        if status.name in self._marked_agent_clis:
            self._marked_agent_clis.remove(status.name)
        else:
            self._marked_agent_clis.add(status.name)
        self._refresh_agent_cli_mark_row(status.name)
        self._advance_agent_cli_mark_selection()
        self._update_static("#agent-clis-hints", self._agent_cli_hints())

    def _can_mark_agent_cli(self, status: AgentCliStatus | None) -> bool:
        return status is not None and self._agent_cli_update_entry(status).ready

    def _refresh_agent_cli_mark_row(self, name: str) -> None:
        option_list = self._agent_cli_option_list()
        status = self._agent_cli_by_name(name)
        if option_list is None or status is None:
            return
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == target:
                option_list.replace_option_prompt_at_index(
                    index, self._agent_cli_row(status)
                )
                return

    def _advance_agent_cli_mark_selection(self) -> None:
        option_list = self._agent_cli_option_list()
        if option_list is None or option_list.highlighted is None:
            return
        start = option_list.highlighted
        for offset in range(1, option_list.option_count + 1):
            index = (start + offset) % option_list.option_count
            option = option_list.get_option_at_index(index)
            status = self._agent_cli_by_name(str(option.id).removeprefix(_ITEM_PREFIX))
            if self._can_mark_agent_cli(status):
                option_list.highlighted = index
                return

    def _clear_agent_cli_marks(self) -> None:
        names = tuple(self._marked_agent_clis)
        self._marked_agent_clis.clear()
        for name in names:
            self._refresh_agent_cli_mark_row(name)
        self._update_static("#agent-clis-hints", self._agent_cli_hints())

    def _prune_agent_cli_marks(self) -> None:
        live = {
            status.name
            for status in self._agent_cli_statuses
            if self._can_mark_agent_cli(status)
        }
        self._marked_agent_clis &= live

    def action_clear_marks_or_close(self) -> None:
        """Clear marks in the active sub-tab before closing the Admin Center."""
        if self._active_subtab == "agent-clis" and self._marked_agent_clis:
            count = len(self._marked_agent_clis)
            self._clear_agent_cli_marks()
            self._notify(f"Cleared {count} agent CLI update mark(s).")
            return
        if self._active_subtab == "plugins" and self._marked_install:
            count = len(self._marked_install)
            self._clear_install_marks()
            self._notify(f"Cleared {count} install mark(s).")
            return
        close = getattr(getattr(self, "screen", None), "action_close", None)
        if callable(close):
            close()

    # -- shared planning + execution ----------------------------------------

    def _agent_cli_update_entry(self, status: AgentCliStatus) -> AgentCliUpdateEntry:
        plan = self._make_agent_cli_update_plan((status.name,), all_clis=False)
        if isinstance(plan, (AgentCliUpdatesReady, AgentCliNothingToUpdate)):
            return plan.entries[0]
        raise RuntimeError(f"Could not plan registered agent CLI {status.name}")

    def _make_agent_cli_update_plan(
        self,
        names: tuple[str, ...] | None,
        *,
        all_clis: bool,
    ) -> AgentCliUpdatePlan:
        from . import plugins_browser_pane as pane_module

        statuses = self._agent_cli_statuses
        return pane_module._plan_agent_cli_updates(
            names,
            all_clis=all_clis,
            refresh=False,
            offline=self._offline,
            status_fn=lambda **_kwargs: statuses,
        )

    def action_update_agent_clis(self) -> None:
        """Plan updates for marked Agent CLIs, or every updatable installed CLI."""
        if self._loading or self._agent_cli_plan_worker is not None:
            return
        names = (
            tuple(sorted(self._marked_agent_clis))
            if self._active_subtab == "agent-clis" and self._marked_agent_clis
            else None
        )
        all_clis = names is None

        def task() -> AgentCliUpdatePlan:
            return self._make_agent_cli_update_plan(names, all_clis=all_clis)

        self._agent_cli_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="agent-cli-update-plan",
            exit_on_error=False,
        )

    def _on_agent_cli_update_preview(self, plan: AgentCliUpdatePlan | None) -> None:
        if plan is None:
            return
        if isinstance(plan, AgentCliUnknownName):
            self._notify(f"Unknown agent CLI: {plan.query}", severity="error")
            return
        if not plan.entries:
            message = self._agent_cli_error or "No agent CLIs are available to update."
            self._notify(message, severity="warning")
            return

        runnable = tuple(entry for entry in plan.entries if entry.argv is not None)
        skipped = tuple(entry for entry in plan.entries if entry.argv is None)
        commands = tuple(
            f"{entry.status.display_name}: {shlex.join(entry.argv or ())}"
            for entry in runnable
        )
        skip_lines = tuple(
            f"{entry.status.display_name}: {entry.skip_reason or 'skipped'}"
            for entry in skipped
        )
        count = len(runnable)
        summary = (
            f"Runs {count} agent CLI update command{'s' if count != 1 else ''} "
            "sequentially"
        )
        modal = PluginActionConfirmModal(
            title="Update agent CLIs",
            intro="Confirm the exact provider update commands below.",
            variants=(
                PluginActionVariant(
                    key="agent-cli-update",
                    label="agent CLIs",
                    argv=(),
                    summary=summary,
                    items=commands,
                    items_label="Commands",
                    skipped=skip_lines,
                ),
            ),
            panel_title="Confirm agent CLI updates",
            icon="↑",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is not None:
                self._submit_agent_cli_update_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_agent_cli_update_task(
        self,
        plan: AgentCliUpdatesReady | AgentCliNothingToUpdate,
    ) -> None:
        from . import plugins_browser_pane as pane_module

        def task(
            reporter: TaskReporter,
        ) -> TrackedTaskResult[tuple[AgentCliUpdateResult, ...]]:
            reporter.phase("Updating agent CLIs")

            def task_runner(
                argv: tuple[str, ...], *, timeout: float = 300.0
            ) -> CommandResult:
                return run_command(
                    argv,
                    timeout=timeout,
                    run_fn=reporter.subprocess_run_fn(),
                )

            results = pane_module._execute_agent_cli_updates(
                plan,
                run_fn=task_runner,
            )
            message = _agent_cli_update_summary(results)
            reporter.section("Results")
            for result in results:
                reporter.log(_agent_cli_result_line(result), stream="result")
            failed = any(
                result.status is UpdateResultStatus.FAILED for result in results
            )
            return TrackedTaskResult(
                success=not failed,
                message=message,
                payload=results,
                error=message if failed else None,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return
        submit(
            "agent-cli-update",
            "agent CLIs",
            "",
            task,
            display_name="update agent CLIs",
            dedup_key="agent-cli-update",
            duplicate_message="An agent CLI update is already running.",
            on_complete=self._on_agent_cli_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    def _on_agent_cli_update_complete(
        self,
        completion: TrackedTaskCompletion[tuple[AgentCliUpdateResult, ...]],
    ) -> None:
        results = completion.payload or ()
        for result in results:
            self._agent_cli_results[result.name] = result
        self._clear_agent_cli_marks()
        self._render_agent_cli_detail(force=True)
        self._notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if self.is_mounted:
            self._start_load(force=False)


def _agent_cli_result_line(result: AgentCliUpdateResult) -> str:
    if result.status is UpdateResultStatus.UPDATED:
        old = result.old_version or "unknown"
        new = result.new_version or "unknown"
        return f"{result.display_name}: updated {old} → {new}"
    if result.status is UpdateResultStatus.ALREADY_CURRENT:
        return f"{result.display_name}: already current"
    if result.status is UpdateResultStatus.FAILED:
        detail = result.reason or "update failed"
        return f"{result.display_name}: failed — {detail}"
    detail = result.reason or "skipped"
    return f"{result.display_name}: skipped — {detail}"


def _agent_cli_update_summary(results: tuple[AgentCliUpdateResult, ...]) -> str:
    """Build the concise completion toast for a batch agent-CLI update."""
    if not results:
        return "No agent CLIs needed an update."
    return "\n".join(_agent_cli_result_line(result) for result in results)
