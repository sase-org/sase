"""Marking, planning, and execution actions for the Agent CLIs browser."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any, Literal

from rich.console import RenderableType

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliStatus,
    AgentCliUnknownName,
    AgentCliUpdateEntry,
    AgentCliUpdatePlan,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateTrigger,
)

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)

if TYPE_CHECKING:
    from rich.text import Text
    from textual.app import App
    from textual.widgets import OptionList
    from textual.worker import Worker

_ITEM_PREFIX = "agent-cli__"


class AgentCliBrowserActionsMixin:
    """Mark, plan, confirm, and execute agent-CLI updates."""

    if TYPE_CHECKING:
        _active_subtab: str
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

        def action_toggle_install_mark(self) -> None: ...

        def _agent_cli_by_name(self, name: str) -> AgentCliStatus | None: ...

        def _agent_cli_hints(self) -> str: ...

        def _agent_cli_option_list(self) -> OptionList | None: ...

        def _agent_cli_row(self, status: AgentCliStatus) -> Text: ...

        def _clear_install_marks(self) -> None: ...

        def _current_agent_cli(self) -> AgentCliStatus | None: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _render_agent_cli_detail(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

    # -- mark handling -------------------------------------------------------

    def action_toggle_mark(self) -> None:
        """Toggle the active Plugins or Agent CLIs mark."""
        if self._active_subtab == "plugins":
            self.action_toggle_install_mark()
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

        def task() -> TrackedProcResult[tuple[AgentCliUpdateResult, ...]]:
            results = pane_module._execute_agent_cli_updates(
                plan,
                trigger=UpdateTrigger.ADMIN_CENTER,
            )
            message = _agent_cli_update_summary(results)
            failed = any(
                result.status is UpdateResultStatus.FAILED for result in results
            )
            return TrackedProcResult(
                success=not failed,
                message=message,
                payload=results,
                error=message if failed else None,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "agent-cli-update",
            task,
            display_name="update agent CLIs",
            cl_name="agent CLIs",
            dedup_key="agent-cli-update",
            exclusive_scopes=("agent-cli-update",),
            duplicate_message="An agent CLI update is already running.",
            on_complete=self._on_agent_cli_update_complete,
        )

    def _on_agent_cli_update_complete(
        self,
        completion: TrackedProcCompletion[tuple[AgentCliUpdateResult, ...]],
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


def agent_cli_result_line(result: AgentCliUpdateResult) -> str:
    if result.status is UpdateResultStatus.UPDATED:
        old = result.old_version or "unknown"
        new = result.new_version or "unknown"
        line = f"{result.display_name}: updated {old} → {new}"
        return f"{line} — {result.reason}" if result.reason else line
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
    return "\n".join(agent_cli_result_line(result) for result in results)
