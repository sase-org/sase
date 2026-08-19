"""Snapshot-gated comprehensive update orchestration for ACE."""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.update_preview_inputs import UpdatePreviewInputs
from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.ace.update_scope import UpdateLeg
from sase.agent_clis.models import AgentCliStatus
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult

from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_comprehensive_update_execution import (
    ComprehensiveUpdateExecutionMixin,
    comprehensive_update_summary,
    order_provider_results,
)
from .plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
    DroppedProviderCandidate,
    error_text,
)
from .plugins_browser_comprehensive_update_preview import (
    agents_preview_section,
    build_comprehensive_update_preview,
    comprehensive_confirm_copy,
    comprehensive_current_message,
    comprehensive_dropped_message,
    comprehensive_preview_sections,
    dev_update_commands,
    plan_captured_providers,
    provider_preview_section,
    sase_preview_section,
)

# Preserve the original module's private helper names for tests and downstream
# imports while keeping their implementations in focused modules.
_ComprehensiveUpdatePreview = ComprehensiveUpdatePreview
_DroppedProviderCandidate = DroppedProviderCandidate
_comprehensive_update_summary = comprehensive_update_summary
_agents_preview_section = agents_preview_section
_dev_update_commands = dev_update_commands
_error_text = error_text
_order_provider_results = order_provider_results
_plan_captured_providers = plan_captured_providers
_provider_preview_section = provider_preview_section
_sase_preview_section = sase_preview_section


class ComprehensiveUpdateActionsMixin(ComprehensiveUpdateExecutionMixin):
    """Plan, confirm, execute, and hand off the global ``,U`` flow."""

    if TYPE_CHECKING:
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _agent_cli_error: str | None
        _agent_cli_results: dict[str, Any]
        _comprehensive_update_plan_worker: Any | None
        _incoming_commits_enabled: bool
        _loading: bool
        _offline: bool
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _close_admin_center_after_sase_update(self) -> None: ...

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

        def _comprehensive_update_incoming_commits_loader(
            self, preview: ComprehensiveUpdatePreview
        ) -> Any | None: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _restart_after_update(self, message: str) -> None: ...

        def _start_load(self, *, force: bool) -> None: ...

    def _start_comprehensive_update_preview(
        self,
        request: ComprehensiveUpdateRequest,
        *,
        already_refreshed_roots: Collection[str] = (),
    ) -> None:
        """Build the selected preview legs off-thread from explicit inputs."""
        if self._loading or self._comprehensive_update_plan_worker is not None:
            return

        cached_status = getattr(self, "_update_status", None)
        if cached_status is None:
            cached_status = getattr(
                getattr(self, "app", None), "_automatic_update_status", None
            )
        inputs = UpdatePreviewInputs(
            uv_tool=self._uv_tool,
            agent_cli_statuses=tuple(self._agent_cli_statuses),
            agent_cli_error=self._agent_cli_error,
            offline=self._offline,
            cached_status=cached_status,
        )
        fresh_roots = frozenset(already_refreshed_roots)

        def task() -> ComprehensiveUpdatePreview:
            return build_comprehensive_update_preview(
                request,
                inputs,
                already_refreshed_roots=fresh_roots,
            )

        self._comprehensive_update_plan_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="comprehensive-update-plan",
            exit_on_error=False,
        )

    def _on_comprehensive_update_preview(
        self, preview: ComprehensiveUpdatePreview | None
    ) -> None:
        if preview is None:
            return
        if not preview.runnable:
            self._handle_comprehensive_noop(preview)
            return

        incoming_loader: Any | None = None
        incoming_empty_message: str | None = None
        if UpdateLeg.SASE in preview.selected_legs:
            incoming_loader = self._comprehensive_update_incoming_commits_loader(
                preview
            )
            if self._incoming_commits_enabled:
                incoming_empty_message = (
                    "No repository commit ranges are available for this update. "
                    "Agent CLI installers and agents-repository synchronization do "
                    "not expose trustworthy commit ranges."
                    if not preview.sase_runnable
                    else "No repository commit ranges are available for the captured "
                    "SASE update."
                )

        title, intro, panel_title = comprehensive_confirm_copy(preview.request.scope)
        modal = PluginActionConfirmModal(
            title=title,
            intro=intro,
            variants=(
                PluginActionVariant(
                    key="comprehensive-update",
                    label="comprehensive update",
                    argv=(),
                    summary="Runs one tracked comprehensive update.",
                    sections=comprehensive_preview_sections(preview),
                ),
            ),
            panel_title=panel_title,
            icon="↑",
            incoming_commits_loader=incoming_loader,
            incoming_commits_empty_message=incoming_empty_message,
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            if self._submit_comprehensive_update_task(preview):
                self._close_admin_center_after_sase_update()

        self.app.push_screen(modal, _on_confirmed)

    def _handle_comprehensive_noop(self, preview: ComprehensiveUpdatePreview) -> None:
        if preview.manual_provider_entries:
            switch_to_subtab = getattr(self, "_switch_to_subtab", None)
            if callable(switch_to_subtab):
                switch_to_subtab("agent-clis")
                self._notify(
                    "No safe automatic Agent CLI command is available. Review the "
                    "manual command and vendor documentation in Agent CLIs.",
                    severity="warning",
                )
            else:
                self._notify(
                    "No safe automatic Agent CLI command is available. Review the "
                    "manual command and vendor documentation in the Admin Center "
                    "Updates tab.",
                    severity="warning",
                )
            return
        selected = preview.selected_legs
        errors = tuple(
            item
            for item, selected_leg in (
                (preview.sase_blocker, UpdateLeg.SASE),
                (preview.provider_error, UpdateLeg.PROVIDERS),
                (preview.agents_error, UpdateLeg.AGENTS),
            )
            if item and selected_leg in selected
        )
        if errors:
            self._notify("; ".join(errors), severity="error")
            return
        if preview.provider_dropped:
            names = ", ".join(item.name for item in preview.provider_dropped)
            self._notify(
                comprehensive_dropped_message(preview.request.scope, names),
                severity="information",
            )
            return
        self._notify(
            comprehensive_current_message(preview.request.scope),
            severity="information",
        )

    def _submit_comprehensive_update_task(
        self, preview: ComprehensiveUpdatePreview
    ) -> bool:
        """Submit exactly one task claiming all update mutation scopes."""

        def task() -> TrackedProcResult[ComprehensiveUpdateResult]:
            start = time.monotonic()
            provider_results, provider_error = self._execute_provider_leg(preview)
            sase_result = self._execute_comprehensive_sase_leg(preview)
            agents_outcomes, agents_error = self._execute_agents_leg(preview)
            result = ComprehensiveUpdateResult(
                sase=sase_result,
                provider_results=provider_results,
                provider_error=provider_error or preview.provider_error,
                agents_outcomes=agents_outcomes,
                agents_error=agents_error or preview.agents_error,
                elapsed=max(0.0, time.monotonic() - start),
            )
            message = comprehensive_update_summary(result)
            return TrackedProcResult(
                success=not result.has_failures,
                message=message,
                payload=result,
                error=message if result.has_failures else None,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return False
        submitted = submit(
            "comprehensive-update",
            task,
            display_name="comprehensive update",
            cl_name="sase + agent CLIs + cached hoods",
            dedup_key="comprehensive-update",
            exclusive_scopes=(
                "sase-update",
                "agent-cli-update",
                "agents-sync",
            ),
            duplicate_message=(
                "A SASE, agent CLI, or agents-repository update is already running."
            ),
            on_complete=self._on_comprehensive_update_complete,
        )
        return submitted is not None

    def _on_comprehensive_update_complete(
        self,
        completion: TrackedProcCompletion[ComprehensiveUpdateResult],
    ) -> None:
        # Even an unexpected task-wrapper failure should promptly reconcile
        # the shared snapshot and badge from local state.
        refresh = getattr(self.app, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()
        refresh_agents = getattr(
            self.app,
            "_schedule_agents_sync_indicator_revalidation",
            None,
        )
        if callable(refresh_agents):
            refresh_agents()

        result = completion.payload
        if result is None:
            self._notify(
                f"comprehensive update failed: {completion.error or completion.message}",
                severity="error",
            )
            return
        if result.agents_outcomes:
            reload_agents = getattr(self.app, "_schedule_agents_async_refresh", None)
            if callable(reload_agents):
                reload_agents(source="comprehensive_cached_agents")

        for provider_result in result.provider_results:
            self._agent_cli_results[provider_result.name] = provider_result

        # Revalidate and rewrite the shared composite snapshot in a worker;
        # this updates the badge promptly without broadening captured authority.
        message = comprehensive_update_summary(result)
        if result.code_changed:
            receipt = build_update_receipt(result)
            if receipt is not None:
                write_pending_update_toast(receipt)
            self._restart_after_update(message)
            return

        severity: Literal["information", "warning", "error"] = "information"
        if result.fully_failed:
            severity = "error"
        elif result.has_failures:
            severity = "warning"
        self._notify(message, severity=severity)
        if self.is_mounted and not self._loading:
            self._start_load(force=False)


__all__ = [
    "ComprehensiveUpdateActionsMixin",
    "ComprehensiveUpdateRequest",
]
