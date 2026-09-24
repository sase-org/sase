"""Mixed plugin + agent-CLI install actions for the plugin browser."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.agent_clis.install import AgentCliInstallsPlanned
from sase.agent_clis.models import (
    AgentCliUnknownName,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)
from sase.plugins.operations import (
    InstallManyNothing,
    InstallManyOutcome,
    InstallManyReady,
    NotUvTool,
)
from sase.uv_tool.errors import UvToolError

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionPreviewComponent,
    PluginActionPreviewSection,
    PluginActionVariant,
)
from .plugins_browser_install_messages import (
    _combined_install_message,
    _install_many_skipped_message,
    install_many_success_message,
    install_many_summary,
)
from .plugins_browser_install_previews import (
    CombinedInstallPreview,
    InstallManyPreview,
    _CombinedInstallOutcome,
)

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

    from .config_center_session import UpdatesSessionState


class PluginCombinedInstallActionsMixin:
    """Mixed agent-CLI + plugin install actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _agent_cli_results: dict[str, AgentCliUpdateResult]
        _offline: bool
        _plan_worker: Worker[Any] | None
        _session_state: UpdatesSessionState
        app: App[Any]
        is_mounted: bool

        def _make_agent_cli_install_plan(
            self, names: tuple[str, ...], *, offline: bool
        ) -> Any: ...

        def _make_install_many_preview(
            self, names: tuple[str, ...], *, offline: bool
        ) -> InstallManyPreview: ...

        def _execute_install_many(
            self, plan: InstallManyReady, *, run_fn: Any = None
        ) -> InstallManyOutcome: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _clear_marks(self, keys: object = None) -> None: ...

        def _marked_keys_with(self, capability: str) -> tuple[str, ...]: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _start_load(self, *, force: bool, cache_only: bool = False) -> None: ...

        def _handle_code_update_completion(
            self,
            completion: TrackedProcCompletion[Any],
            *,
            failure_prefix: str,
        ) -> None: ...

    def _begin_combined_install_plan(
        self, cli_names: tuple[str, ...], plugin_names: tuple[str, ...]
    ) -> None:
        """Plan a mixed agent-CLI + plugin install off the event loop."""
        offline = self._offline

        def task() -> CombinedInstallPreview:
            cli_plan = self._make_agent_cli_install_plan(cli_names, offline=offline)
            plugin_preview = self._make_install_many_preview(
                plugin_names, offline=offline
            )
            return CombinedInstallPreview(
                cli_names=cli_names,
                plugin_names=plugin_names,
                cli_plan=cli_plan,
                plugin_preview=plugin_preview,
            )

        self._plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task, thread=True, exclusive=True, group="plugin-plan"
        )

    def _combined_plugin_skip_reason(self, preview: InstallManyPreview) -> str | None:
        """The plugin-half skip reason, or None when the plugins can install."""
        if preview.error is not None:
            return f"Plugins: {preview.error}"
        plan = preview.plan
        if isinstance(plan, NotUvTool):
            return str(plan.error)
        if isinstance(plan, InstallManyNothing):
            skipped = "; ".join(
                _install_many_skipped_message(item) for item in plan.skipped
            )
            suffix = f": {skipped}" if skipped else "."
            return f"No marked plugins can be installed{suffix}"
        return None

    def _on_combined_install_preview(self, preview: CombinedInstallPreview) -> None:
        """Route a mixed install preview to a toast or the combined modal."""
        from .plugins_browser_agent_clis_install import agent_cli_install_skip_line

        cli_plan = preview.cli_plan
        if isinstance(cli_plan, AgentCliUnknownName):
            self._notify(f"Unknown agent CLI: {cli_plan.query}", severity="error")
            return
        cli_ready = cli_plan.runnable_entries
        plugin_skip = self._combined_plugin_skip_reason(preview.plugin_preview)
        plugin_plan = preview.plugin_preview.plan
        plugin_ready = (
            plugin_plan if isinstance(plugin_plan, InstallManyReady) else None
        )
        if not cli_ready and plugin_ready is None:
            cli_plan.cleanup()
            reasons = "; ".join(
                [
                    *(agent_cli_install_skip_line(entry) for entry in cli_plan.entries),
                    *((plugin_skip,) if plugin_skip else ()),
                ]
            )
            self._notify(
                f"Nothing marked can be installed: {reasons}"
                if reasons
                else "Nothing marked can be installed.",
                severity="warning",
            )
            return
        self._open_combined_install_modal(preview, cli_ready, plugin_ready)

    def _open_combined_install_modal(
        self,
        preview: CombinedInstallPreview,
        cli_ready: tuple[Any, ...],
        plugin_ready: InstallManyReady | None,
    ) -> None:
        """Preview a mixed install: agent-CLI sections plus a Plugins section."""
        from .plugins_browser_agent_clis_install import (
            agent_cli_install_entry_section,
            agent_cli_install_skip_line,
        )

        sections: list[PluginActionPreviewSection] = [
            agent_cli_install_entry_section(entry) for entry in cli_ready
        ]
        skipped: list[str] = []
        if isinstance(preview.cli_plan, AgentCliInstallsPlanned):
            skipped.extend(
                agent_cli_install_skip_line(entry)
                for entry in preview.cli_plan.entries
                if not entry.ready
            )
        details: list[str] = [
            "Runs without a shell · never edits your shell startup files"
        ]
        if plugin_ready is not None:
            sections.append(
                PluginActionPreviewSection(
                    title="Plugins",
                    summary=install_many_summary(plugin_ready),
                    components=tuple(
                        PluginActionPreviewComponent(
                            spec.display_name, f"from {spec.source}", "update"
                        )
                        for spec in plugin_ready.specs
                    ),
                    commands=(shlex.join(tuple(plugin_ready.argv)),),
                    counts=(
                        f"{len(plugin_ready.specs)} "
                        f"{'plugin' if len(plugin_ready.specs) == 1 else 'plugins'}",
                    ),
                )
            )
            details.insert(0, "sase's TUI restarts after the plugins install.")
        else:
            plugin_skip = self._combined_plugin_skip_reason(preview.plugin_preview)
            if plugin_skip is not None:
                skipped.append(plugin_skip)
        plugin_count = len(plugin_ready.specs) if plugin_ready is not None else 0
        cli_count = len(cli_ready)
        title_parts: list[str] = []
        if plugin_count:
            noun = "plugin" if plugin_count == 1 else "plugins"
            title_parts.append(f"{plugin_count} {noun}")
        if cli_count:
            noun = "agent CLI" if cli_count == 1 else "agent CLIs"
            title_parts.append(f"{cli_count} {noun}")
        summary = (
            f"Installs {' and '.join(title_parts)}, agent CLIs first, one at a time"
            if plugin_ready is not None and cli_count
            else f"Installs {' and '.join(title_parts)}"
        )
        modal = PluginActionConfirmModal(
            title=f"Install {' and '.join(title_parts)}",
            intro="Confirm the exact install commands below.",
            variants=[
                PluginActionVariant(
                    key="combined",
                    label="marked set",
                    argv=(),
                    summary=summary,
                    skipped=tuple(skipped),
                    details=tuple(details),
                    sections=tuple(sections),
                )
            ],
            panel_title="Confirm install",
            icon="↓",
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                if isinstance(preview.cli_plan, AgentCliInstallsPlanned):
                    preview.cli_plan.cleanup()
                return
            self._submit_combined_install_task(preview)

        self.app.push_screen(modal, _on_confirmed)

    def _submit_combined_install_task(self, preview: CombinedInstallPreview) -> None:
        """Install agent CLIs first, then plugins, in one session proc.

        CLIs run first so the TUI restart after a plugin change can never
        interrupt an installer. The TUI restarts only if the plugins changed.
        """
        from . import plugins_browser_pane as pane_module
        from .plugins_browser_agent_clis_actions import (
            agent_cli_result_line,
        )

        assert isinstance(preview.cli_plan, AgentCliInstallsPlanned)
        cli_plan = preview.cli_plan
        plugin_preview = preview.plugin_preview
        plugin_plan = (
            plugin_preview.plan
            if isinstance(plugin_preview.plan, InstallManyReady)
            else None
        )
        runnable_total = len(cli_plan.runnable_entries)

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[_CombinedInstallOutcome]:
            reporter.phase("Installing agent CLIs")

            def _progress(index: int, _total: int, entry: Any) -> None:
                reporter.phase(
                    f"Installing {entry.status.display_name} ({index}/{runnable_total})"
                )

            try:
                cli_results = pane_module._execute_agent_cli_installs(
                    cli_plan,
                    run_fn=reporter.command_runner(),
                    trigger=UpdateTrigger.ADMIN_CENTER,
                    progress_fn=_progress,
                )
            finally:
                cli_plan.cleanup()
            reporter.section("Results")
            for result in cli_results:
                reporter.log(agent_cli_result_line(result), stream="result")
            plugin_outcome: InstallManyOutcome | None = None
            plugin_error: str | None = None
            if plugin_plan is not None:
                try:
                    count = len(plugin_plan.specs)
                    reporter.phase(f"Installing {count} marked plugin(s)")
                    plugin_outcome = self._execute_install_many(
                        plugin_plan, run_fn=reporter.uv_runner()
                    )
                except UvToolError as exc:
                    plugin_error = str(exc)
            outcome = _CombinedInstallOutcome(
                cli_results=cli_results,
                plugin_outcome=plugin_outcome,
                plugin_error=plugin_error,
            )
            cli_failed = any(
                result.status is UpdateResultStatus.FAILED for result in cli_results
            )
            return TrackedProcResult(
                success=not cli_failed and plugin_error is None,
                message=_combined_install_message(outcome),
                payload=outcome,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            cli_plan.cleanup()
            return
        submitted = submit(
            "agent-cli-plugin-install",
            task,
            display_name="install marked plugins and agent CLIs",
            cl_name=", ".join([*preview.plugin_names, *preview.cli_names]),
            dedup_key="agent-cli-plugin-install",
            exclusive_scopes=("agent-cli-update",),
            duplicate_message="An install is already running.",
            on_complete=self._on_combined_install_complete,
        )
        if submitted is None:
            cli_plan.cleanup()

    def _on_combined_install_complete(
        self, completion: TrackedProcCompletion[_CombinedInstallOutcome]
    ) -> None:
        """Apply CLI results, clear install marks, and finish the plugin leg."""
        from .plugins_browser_agent_clis_actions import agent_cli_install_summary

        try:
            self._session_state.invalidate_inventory()
        except Exception:
            pass
        outcome = completion.payload
        if outcome is None:
            return
        for result in outcome.cli_results:
            self._agent_cli_results[result.name] = result
        self._clear_marks(self._marked_keys_with("install"))
        self._render_detail_now(force=True)
        cli_message, cli_severity = agent_cli_install_summary(outcome.cli_results)
        if outcome.plugin_outcome is None and outcome.plugin_error is None:
            self._notify(cli_message, severity=cli_severity)
            if self.is_mounted:
                self._start_load(force=False)
            return
        if outcome.plugin_error is not None:
            plugin_completion = TrackedProcCompletion[InstallManyOutcome](
                proc_info=completion.proc_info,
                success=False,
                message=f"{cli_message}\n{outcome.plugin_error}",
                output=completion.output,
                payload=None,
                error=outcome.plugin_error,
            )
        else:
            assert outcome.plugin_outcome is not None
            plugin_message = install_many_success_message(outcome.plugin_outcome)
            plugin_completion = TrackedProcCompletion[InstallManyOutcome](
                proc_info=completion.proc_info,
                success=True,
                message=f"{cli_message}\n{plugin_message}",
                output=completion.output,
                payload=outcome.plugin_outcome,
            )
        self._handle_code_update_completion(
            plugin_completion,
            failure_prefix="Install failed",
        )
