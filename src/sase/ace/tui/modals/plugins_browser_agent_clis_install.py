"""Agent-CLI install planning, preview, and execution for the Updates tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.agent_clis.cli_update import command_text
from sase.agent_clis.install import AgentCliInstallEntry, AgentCliInstallsPlanned
from sase.agent_clis.models import (
    AgentCliUnknownName,
    AgentCliUpdateResult,
    InstallRoute,
    UpdateResultStatus,
    UpdateTrigger,
)

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionPreviewSection,
    PluginActionVariant,
)
from .plugins_browser_agent_clis_actions import (
    agent_cli_install_summary,
    agent_cli_result_line,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

    from sase.agent_clis.install import AgentCliInstallPlan

    from .plugins_browser_rows import UpdateRow

_ROUTE_LABELS: dict[InstallRoute, str] = {
    InstallRoute.NPM: "npm",
    InstallRoute.SCRIPT: "install script",
    InstallRoute.MANUAL: "manual",
    InstallRoute.BUNDLED: "bundled",
}


def _agent_cli_install_route_label(entry: AgentCliInstallEntry) -> str:
    """The short installer label shown in the confirm preview."""
    return _ROUTE_LABELS.get(entry.route, entry.route.value)


def agent_cli_install_entry_section(
    entry: AgentCliInstallEntry,
) -> PluginActionPreviewSection:
    """Build one confirm-preview section for a runnable install entry."""
    status = entry.status
    counts = [_agent_cli_install_route_label(entry)]
    if status.latest_version:
        counts.append(f"latest v{status.latest_version}")
    details: list[str] = []
    if entry.script is not None:
        details.append(f"script {entry.script.url} · {entry.script.size_bytes} bytes")
        details.append(f"sha256 {entry.script.digest}")
    if entry.install_dir:
        target = f"target {entry.install_dir}"
        if entry.install_dir_on_path is True:
            target += " · on PATH"
        elif entry.install_dir_on_path is False:
            target += " · not on PATH (SASE prints the export line)"
        details.append(target)
    commands: tuple[str, ...] = ()
    if entry.argv is not None:
        commands = (command_text(entry.argv, entry.env_overlay),)
    return PluginActionPreviewSection(
        title=status.display_name,
        counts=tuple(counts),
        details=tuple(details),
        commands=commands,
    )


def agent_cli_install_skip_line(entry: AgentCliInstallEntry) -> str:
    """The variant-level skip line for an entry that cannot be installed."""
    reason = entry.skip_reason or entry.error or "skipped"
    return f"{entry.status.display_name}: {reason}"


def agent_cli_install_variant(plan: AgentCliInstallsPlanned) -> PluginActionVariant:
    """Build the confirm-modal variant for a planned agent-CLI install."""
    runnable = plan.runnable_entries
    count = len(runnable)
    noun = "agent CLI" if count == 1 else "agent CLIs"
    skipped = tuple(
        agent_cli_install_skip_line(entry) for entry in plan.entries if not entry.ready
    )
    return PluginActionVariant(
        key="agent-cli-install",
        label="agent CLIs",
        argv=(),
        summary=f"Installs {count} {noun}, one at a time",
        skipped=skipped,
        details=("Runs without a shell · never edits your shell startup files",),
        sections=tuple(agent_cli_install_entry_section(entry) for entry in runnable),
    )


def agent_cli_install_modal_title(plan: AgentCliInstallsPlanned) -> str:
    """The confirm-modal title for a planned agent-CLI install."""
    runnable = plan.runnable_entries
    if len(runnable) == 1:
        return f"Install {runnable[0].status.display_name}"
    return f"Install {len(runnable)} agent CLIs"


class AgentCliInstallActionsMixin:
    """Plan, preview, and execute agent-CLI installs from the Updates tab."""

    if TYPE_CHECKING:
        from .config_center_session import UpdatesSessionState

        _agent_cli_install_plan_worker: Worker[Any] | None
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _agent_cli_statuses: tuple[Any, ...]
        _loading: bool
        _marked: set[str]
        _offline: bool
        _session_state: UpdatesSessionState
        app: App[Any]
        is_mounted: bool

        def _clear_marks(self, keys: object = None) -> None: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _make_agent_cli_install_plan(
            self, names: tuple[str, ...], *, offline: bool
        ) -> AgentCliInstallPlan: ...

        def _marked_keys_with(self, capability: str) -> tuple[str, ...]: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool, cache_only: bool = False) -> None: ...

        def _update_static(self, selector: str, content: Any) -> None: ...

        def _hints(self) -> str: ...

    def _begin_agent_cli_install_plan(self, names: tuple[str, ...]) -> None:
        """Plan an agent-CLI install off the event loop, then preview it."""
        offline = self._offline

        def task() -> AgentCliInstallPlan:
            return self._make_agent_cli_install_plan(names, offline=offline)

        self._agent_cli_install_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="agent-cli-install-plan",
            exit_on_error=False,
        )
        self._update_static("#updates-hints", self._hints())

    def _on_agent_cli_install_preview(self, plan: AgentCliInstallPlan | None) -> None:
        """Route a planned agent-CLI install to a toast or the confirm modal."""
        if plan is None:
            return
        if isinstance(plan, AgentCliUnknownName):
            self._notify(f"Unknown agent CLI: {plan.query}", severity="error")
            return
        runnable = plan.runnable_entries
        if not runnable:
            reasons = "; ".join(
                agent_cli_install_skip_line(entry) for entry in plan.entries
            )
            plan.cleanup()
            self._notify(
                f"Cannot install: {reasons}"
                if reasons
                else "No agent CLIs can be installed.",
                severity="warning",
            )
            return
        self._open_agent_cli_install_modal(plan)

    def _open_agent_cli_install_modal(self, plan: AgentCliInstallsPlanned) -> None:
        modal = PluginActionConfirmModal(
            title=agent_cli_install_modal_title(plan),
            intro="Confirm the exact install commands below.",
            variants=(agent_cli_install_variant(plan),),
            panel_title="Confirm agent CLI install",
            icon="↓",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                plan.cleanup()
                return
            self._submit_agent_cli_install_task(plan)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_agent_cli_install_task(self, plan: AgentCliInstallsPlanned) -> None:
        """Run the planned installers sequentially in a tracked session proc."""
        from . import plugins_browser_pane as pane_module

        runnable_total = len(plan.runnable_entries)

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[tuple[AgentCliUpdateResult, ...]]:
            reporter.phase("Installing agent CLIs")

            def _progress(index: int, _total: int, entry: AgentCliInstallEntry) -> None:
                reporter.phase(
                    f"Installing {entry.status.display_name} ({index}/{runnable_total})"
                )

            try:
                results = pane_module._execute_agent_cli_installs(
                    plan,
                    run_fn=reporter.command_runner(),
                    trigger=UpdateTrigger.ADMIN_CENTER,
                    progress_fn=_progress,
                )
            finally:
                plan.cleanup()
            message, _severity = agent_cli_install_summary(results)
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
            plan.cleanup()
            return
        names = tuple(entry.status.display_name for entry in plan.runnable_entries)
        submitted = submit(
            "agent-cli-install",
            task,
            display_name="install agent CLIs",
            cl_name=", ".join(names),
            dedup_key="agent-cli-install",
            exclusive_scopes=("agent-cli-update",),
            duplicate_message="An agent CLI install or update is already running.",
            on_complete=self._on_agent_cli_install_complete,
        )
        if submitted is None:
            plan.cleanup()

    def _on_agent_cli_install_complete(
        self,
        completion: TrackedProcCompletion[tuple[AgentCliUpdateResult, ...]],
    ) -> None:
        """Record install results, clear install marks, and reload inventory."""
        try:
            self._session_state.invalidate_inventory()
        except Exception:
            pass
        results = completion.payload or ()
        for result in results:
            self._agent_cli_results[result.name] = result
        self._clear_marks(tuple(f"cli:{result.name}" for result in results))
        self._render_detail_now(force=True)
        message, severity = agent_cli_install_summary(results)
        self._notify(message, severity=severity)
        if self.is_mounted:
            self._start_load(force=False)
