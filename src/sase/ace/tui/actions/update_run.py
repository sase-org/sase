"""App-level comprehensive-update preview, confirmation, and execution."""

from __future__ import annotations

import time
from typing import Literal

from sase.ace.comprehensive_update import ComprehensiveUpdateResult
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_execution import (
    comprehensive_update_summary,
    run_scoped_update,
    scoped_preview_cl_name,
    scoped_update_proc_names,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
    error_text,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_preview import (
    build_comprehensive_update_preview,
    comprehensive_confirm_copy,
    comprehensive_preview_sections,
    handle_comprehensive_noop,
)
from sase.ace.tui.modals.update_panel import UpdatePanel
from sase.ace.tui.update_panel_state import build_update_panel_state
from sase.ace.tui.update_preview_inputs import collect_update_preview_inputs
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.ace.tui.update_restart import restart_after_update
from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.ace.update_scope import UpdateLeg

from .proc_actions import TrackedProcCompletion, TrackedProcResult


class UpdateRunActionsMixin:
    """Plan and run scoped updates without an Admin Center pane mounted."""

    def on_update_panel_recheck_requested(self, event: object) -> None:
        """Re-run the existing periodic checks and mark the open panel busy."""
        if not isinstance(event, UpdatePanel.RecheckRequested):
            return
        self._refresh_open_update_panel(rechecking=True)
        schedule_update = getattr(self, "_schedule_automatic_update_check", None)
        if callable(schedule_update):
            schedule_update(periodic=True, force=True)

    def _refresh_open_update_panel(self, *, rechecking: bool | None = None) -> None:
        """Rebuild the active Update panel from cached snapshots; otherwise no-op."""
        try:
            screen = self.screen  # type: ignore[attr-defined]
        except Exception:
            return
        if not isinstance(screen, UpdatePanel):
            return
        if rechecking is None:
            rechecking = bool(getattr(self, "_automatic_update_check_in_flight", False))
        screen.set_state(
            build_update_panel_state(
                getattr(self, "_automatic_update_status", None),
                now=time.time(),
                rechecking=rechecking,
            )
        )

    def _submit_update_preview_proc(self, request: ComprehensiveUpdateRequest) -> bool:
        """Submit a read-only planning proc for the selected update scope."""
        cached_status = getattr(self, "_automatic_update_status", None)

        def task() -> TrackedProcResult[ComprehensiveUpdatePreview]:
            try:
                inputs = collect_update_preview_inputs(
                    cached_status=cached_status,
                    legs=request.scope.legs,
                )
                preview = build_comprehensive_update_preview(request, inputs)
            except Exception as exc:  # noqa: BLE001 - planning must stay toastable.
                message = error_text(exc)
                return TrackedProcResult(
                    success=False,
                    message=message,
                    error=message,
                )
            return TrackedProcResult(
                success=True,
                message="planned update",
                payload=preview,
            )

        submit = getattr(self, "_submit_session_worker", None)
        if not callable(submit):
            return False
        submitted = submit(
            "update-preview",
            task,
            display_name="plan update",
            cl_name=scoped_preview_cl_name(request.scope),
            dedup_key="update-preview",
            exclusive_scopes=(),
            duplicate_message="An update is already being planned.",
            on_complete=self._on_update_preview_complete,
        )
        return submitted is not None

    def _on_update_preview_complete(
        self,
        completion: TrackedProcCompletion[ComprehensiveUpdatePreview],
    ) -> None:
        preview = completion.payload
        if preview is None:
            self._notify(
                f"update preview failed: {completion.error or completion.message}",
                severity="error",
            )
            return
        if not preview.runnable:
            self._handle_comprehensive_noop(preview)
            return
        if preview.request.auto_approve:
            self._submit_scoped_update_task(preview)
            return

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
        )

        def _on_confirmed(result: PluginActionConfirmResult | None) -> None:
            if result is None:
                return
            self._submit_scoped_update_task(preview)

        self.push_screen(modal, _on_confirmed)  # type: ignore[attr-defined]

    def _handle_comprehensive_noop(self, preview: ComprehensiveUpdatePreview) -> None:
        handle_comprehensive_noop(preview, notify=self._notify)

    def _submit_scoped_update_task(self, preview: ComprehensiveUpdatePreview) -> bool:
        """Submit exactly one task claiming all update mutation scopes."""

        def task(
            reporter: SessionProcReporter,
        ) -> TrackedProcResult[ComprehensiveUpdateResult]:
            uv_tool = None
            if UpdateLeg.SASE in preview.selected_legs:
                from sase.ace.tui.modals.plugins_browser_loading import probe_uv_tool

                uv_tool = probe_uv_tool()
            result = run_scoped_update(preview, uv_tool, reporter=reporter)
            message = comprehensive_update_summary(result)
            reporter.section("Summary")
            reporter.log(message, stream="result")
            return TrackedProcResult(
                success=not result.has_failures,
                message=message,
                payload=result,
                error=message if result.has_failures else None,
            )

        submit = getattr(self, "_submit_session_worker", None)
        if not callable(submit):
            return False
        display_name, cl_name = scoped_update_proc_names(preview.request.scope)
        submitted = submit(
            "comprehensive-update",
            task,
            display_name=display_name,
            cl_name=cl_name,
            dedup_key="comprehensive-update",
            exclusive_scopes=(
                "sase-update",
                "agent-cli-update",
            ),
            duplicate_message="A SASE or agent CLI update is already running.",
            on_complete=self._on_scoped_update_complete,
        )
        return submitted is not None

    def _on_scoped_update_complete(
        self,
        completion: TrackedProcCompletion[ComprehensiveUpdateResult],
    ) -> None:
        refresh = getattr(self, "_schedule_updates_indicator_revalidation", None)
        if callable(refresh):
            refresh()

        result = completion.payload
        if result is None:
            self._notify(
                f"comprehensive update failed: {completion.error or completion.message}",
                severity="error",
            )
            return

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

    def _restart_after_update(self, message: str) -> None:
        restart_after_update(self, message, notify=self._notify)

    def _notify(
        self,
        message: str,
        *,
        severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        notify = getattr(self, "notify", None)
        if callable(notify):
            notify(message, severity=severity)


__all__ = ["UpdateRunActionsMixin"]
