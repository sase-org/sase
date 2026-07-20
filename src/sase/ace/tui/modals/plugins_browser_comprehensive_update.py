"""Snapshot-gated comprehensive update orchestration for ACE."""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_subprocess import TaskReporter
from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.agent_clis.models import AgentCliStatus
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError

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
    dev_update_commands,
    plan_captured_providers,
    provider_preview_section,
    sase_preview_section,
)
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_blocking_reason,
)
from .plugins_browser_sase_update_summary import load_receipt_for_summary

# Preserve the original module's private helper names for tests and downstream
# imports while keeping their implementations in focused modules.
_ComprehensiveUpdatePreview = ComprehensiveUpdatePreview
_DroppedProviderCandidate = DroppedProviderCandidate
_comprehensive_update_summary = comprehensive_update_summary
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
        _loading: bool
        _offline: bool
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _all_up_to_date(self) -> bool: ...

        def _close_admin_center_after_sase_update(self) -> None: ...

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

        def _make_sase_update_preview(
            self,
            receipt: object | None,
            *,
            already_refreshed_roots: Collection[str] = (),
        ) -> DevUpdatePreview: ...

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
        """Build both preview legs off-thread from captured and loaded state."""
        if self._loading or self._comprehensive_update_plan_worker is not None:
            return

        statuses = tuple(self._agent_cli_statuses)
        agent_cli_error = self._agent_cli_error
        offline = self._offline
        install = self._uv_tool
        fresh_roots = frozenset(already_refreshed_roots)
        sase_current = self._all_up_to_date()

        def task() -> ComprehensiveUpdatePreview:
            provider_plan, dropped, provider_error = plan_captured_providers(
                request.provider_names,
                statuses,
                offline=offline,
                source_error=agent_cli_error,
            )
            if sase_current:
                return ComprehensiveUpdatePreview(
                    request=request,
                    sase_preview=None,
                    sase_current=True,
                    provider_plan=provider_plan,
                    provider_dropped=dropped,
                    provider_error=provider_error,
                )
            if isinstance(install, NotUvToolInstall):
                return ComprehensiveUpdatePreview(
                    request=request,
                    sase_preview=None,
                    sase_blocker=str(NotAUvToolInstallError(install)),
                    provider_plan=provider_plan,
                    provider_dropped=dropped,
                    provider_error=provider_error,
                )
            try:
                receipt = load_receipt_for_summary(install)
                sase_preview = self._make_sase_update_preview(
                    receipt,
                    already_refreshed_roots=fresh_roots,
                )
                blocker = sase_preview.error
                if blocker is None and sase_preview.plan is not None:
                    plan_blocker = dev_update_blocking_reason(sase_preview.plan)
                    managed_can_proceed = bool(
                        sase_preview.managed_argv
                        and not sase_preview.plan.actionable_roots
                    )
                    if plan_blocker is not None and not managed_can_proceed:
                        blocker = plan_blocker
            except Exception as exc:  # noqa: BLE001 - preserve provider leg.
                sase_preview = None
                blocker = error_text(exc)
            return ComprehensiveUpdatePreview(
                request=request,
                sase_preview=sase_preview,
                sase_blocker=blocker,
                provider_plan=provider_plan,
                provider_dropped=dropped,
                provider_error=provider_error,
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

        modal = PluginActionConfirmModal(
            title="Comprehensive update",
            intro=(
                "Confirm the snapshot-gated SASE and provider work below. "
                "Provider commands run first and sequentially."
            ),
            variants=(
                PluginActionVariant(
                    key="comprehensive-update",
                    label="comprehensive update",
                    argv=(),
                    summary="Runs one tracked comprehensive update.",
                    sections=(
                        sase_preview_section(preview),
                        provider_preview_section(preview),
                    ),
                ),
            ),
            panel_title="Confirm comprehensive update",
            icon="↑",
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
            return
        errors = tuple(
            item for item in (preview.sase_blocker, preview.provider_error) if item
        )
        if errors:
            self._notify("; ".join(errors), severity="error")
            return
        if preview.provider_dropped:
            names = ", ".join(item.name for item in preview.provider_dropped)
            self._notify(
                "No captured updates remain: available components are current; "
                f"no longer present: {names}.",
                severity="information",
            )
            return
        self._notify(
            "Everything in the captured comprehensive update is already current.",
            severity="information",
        )

    def _submit_comprehensive_update_task(
        self, preview: ComprehensiveUpdatePreview
    ) -> bool:
        """Submit exactly one task claiming both update mutation scopes."""

        def task(
            reporter: TaskReporter,
        ) -> TrackedTaskResult[ComprehensiveUpdateResult]:
            start = time.monotonic()
            provider_results, provider_error = self._execute_provider_leg(
                preview, reporter
            )
            sase_result = self._execute_comprehensive_sase_leg(preview, reporter)
            result = ComprehensiveUpdateResult(
                sase=sase_result,
                provider_results=provider_results,
                provider_error=provider_error or preview.provider_error,
                elapsed=max(0.0, time.monotonic() - start),
            )
            message = comprehensive_update_summary(result)
            reporter.section("Summary")
            reporter.log(message, stream="result")
            return TrackedTaskResult(
                success=not result.has_failures,
                message=message,
                payload=result,
                error=message if result.has_failures else None,
            )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            return False
        task_info = submit(
            "comprehensive-update",
            "sase + agent CLIs",
            "",
            task,
            display_name="comprehensive update",
            dedup_key="comprehensive-update",
            exclusive_scopes=("sase-update", "agent-cli-update"),
            duplicate_message="A SASE or agent CLI update is already running.",
            on_complete=self._on_comprehensive_update_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return task_info is not None

    def _on_comprehensive_update_complete(
        self,
        completion: TrackedTaskCompletion[ComprehensiveUpdateResult],
    ) -> None:
        # Even an unexpected task-wrapper failure should promptly reconcile
        # the shared snapshot and badge from local state.
        refresh = getattr(self.app, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()

        result = completion.payload
        if result is None:
            self._notify(
                f"comprehensive update failed: {completion.error or completion.message}",
                severity="error",
            )
            return

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
