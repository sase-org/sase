"""Marking, planning, and execution actions for the Agent CLIs browser."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any, Literal

from rich.console import RenderableType

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.session_proc_reporter import SessionProcReporter
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
    from textual.app import App
    from textual.worker import Worker

    from .plugins_browser_rows import UpdateRow


class AgentCliBrowserActionsMixin:
    """Mark, plan, confirm, and execute agent-CLI updates."""

    if TYPE_CHECKING:
        _agent_cli_error: str | None
        _agent_cli_plan_worker: Worker[Any] | None
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _loading: bool
        _marked: set[str]
        _offline: bool
        _plan_worker: Worker[Any] | None
        app: App[Any]
        is_mounted: bool

        def _advance_mark_selection(self, capability: str) -> None: ...

        def _clear_marks(self, keys: object = None) -> None: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _hints(self) -> str: ...

        def _marked_cli_names(self) -> tuple[str, ...]: ...

        def _marked_keys_with(self, capability: str) -> tuple[str, ...]: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _refresh_row(self, key: str) -> bool: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

    # -- mark handling -------------------------------------------------------

    def action_toggle_mark(self) -> None:
        """Toggle the mark for the highlighted row; the verb follows the row."""
        if (
            self._loading
            or self._plan_worker is not None
            or self._agent_cli_plan_worker is not None
        ):
            return
        row = self._highlighted_row()
        if row is None:
            self._notify(
                "Select an installable plugin or an updatable agent CLI to mark.",
                severity="warning",
            )
            return
        if "install" in row.capabilities:
            capability = "install"
        elif "mark_update" in row.capabilities:
            capability = "mark_update"
        else:
            self._notify(_unmarkable_message(row), severity="warning")
            return
        if row.key in self._marked:
            self._marked.remove(row.key)
        else:
            self._marked.add(row.key)
        self._refresh_row(row.key)
        self._advance_mark_selection(capability)
        self._update_static("#updates-hints", self._hints())

    def action_clear_marks_or_close(self) -> None:
        """Clear every mark, including filter-hidden ones; close when none are set."""
        if self._marked:
            count = len(self._marked)
            self._clear_marks()
            self._notify(f"Cleared {count} mark(s).")
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
        marked_names = self._marked_cli_names()
        names = marked_names or None
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
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[tuple[AgentCliUpdateResult, ...]]:
            reporter.phase("Updating agent CLIs")
            results = pane_module._execute_agent_cli_updates(
                plan,
                run_fn=reporter.command_runner(),
                trigger=UpdateTrigger.ADMIN_CENTER,
            )
            message = _agent_cli_update_summary(results)
            reporter.section("Results")
            for result in results:
                reporter.log(agent_cli_result_line(result), stream="result")
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
        self._clear_marks(self._marked_keys_with("mark_update"))
        self._render_detail_now(force=True)
        self._notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if self.is_mounted:
            self._start_load(force=False)


def _unmarkable_message(row: UpdateRow) -> str:
    """Kind-specific toast when Space/I is pressed on a row that cannot be marked."""
    if row.kind == "plugin":
        return "Select an installable plugin to mark."
    if row.kind == "agent-cli":
        return "Select an updatable agent CLI to mark."
    return "Select an installable plugin or an updatable agent CLI to mark."


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
