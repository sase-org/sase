"""Tracked-proc execution and restart handling for SASE self-updates."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.update_receipt import build_update_receipt, write_pending_update_toast
from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.dev_update.journal import append_dev_update_journal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.main.update_types import CombinedUpdateResult
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.render import PlannedPackage, UpdateSummary
from sase.uv_tool.runner import run_uv

from .plugins_browser_dev_update import (
    DevUpdatePreview,
    dev_update_failed,
    dev_update_failure_message,
    dev_update_success_message,
)
from .plugins_browser_sase_update_summary import (
    SASE_UPDATE_NOOP_MESSAGE,
    combined_sase_update_success_message,
    managed_update_changed,
    sase_update_success_message,
)


class SaseUpdateProcMixin:
    """Execute SASE updates through the shared tracked-proc system."""

    if TYPE_CHECKING:
        _loading: bool
        _uv_tool: object | None
        app: Any
        is_mounted: bool

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _run_sase_update_summary(
            self, install: object | None, *, run_fn: Any = run_uv
        ) -> tuple[UpdateSummary, float]: ...

        def _run_planned_sase_update_summary(
            self,
            argv: tuple[str, ...],
            packages: tuple[PlannedPackage, ...],
            *,
            run_fn: Any = run_uv,
        ) -> tuple[UpdateSummary, float]: ...

        def _execute_dev_update(
            self, plan: DevUpdatePlan, *, run: Any = None
        ) -> DevUpdateResult: ...

        def _start_load(self, *, force: bool) -> None: ...

    def _submit_sase_update_proc(self) -> None:
        """Run the self-update engine in the shared tracked-proc system."""
        install = self._uv_tool

        def proc() -> TrackedProcResult[UpdateSummary]:
            try:
                summary, elapsed = self._run_sase_update_summary(install)
            except UvToolError as exc:
                return TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            message = sase_update_success_message(summary, elapsed)
            return TrackedProcResult(
                success=True,
                message=message,
                payload=summary,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "sase-update",
            proc,
            display_name="sase update",
            cl_name="sase",
            dedup_key="sase-update",
            exclusive_scopes=("sase-update",),
            on_complete=self._on_sase_update_complete,
        )

    def _on_sase_update_complete(
        self, completion: TrackedProcCompletion[UpdateSummary]
    ) -> None:
        """Toast the outcome and refresh installed/latest versions in place."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="sase update failed",
            unchanged_message=SASE_UPDATE_NOOP_MESSAGE,
            unchanged_severity="error",
        )

    def _submit_dev_update_proc(
        self,
        plan: DevUpdatePlan,
        *,
        subject: str,
        display_name: str,
        dedup_key: str,
        duplicate_message: str,
    ) -> None:
        """Run a dev-update plan in the shared tracked-proc system."""

        def proc() -> TrackedProcResult[DevUpdateResult]:
            start = time.monotonic()
            result = self._execute_dev_update(plan)
            append_dev_update_journal(plan, result)
            elapsed = max(0.0, time.monotonic() - start)
            if dev_update_failed(result):
                reason = dev_update_failure_message(result)
                return TrackedProcResult(
                    success=False,
                    message=reason,
                    error=reason,
                    payload=result,
                )
            message = dev_update_success_message(
                result, subject=subject, elapsed=elapsed
            )
            return TrackedProcResult(
                success=True,
                message=message,
                payload=result,
            )

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "dev-update",
            proc,
            display_name=display_name,
            cl_name=subject,
            dedup_key=dedup_key,
            exclusive_scopes=("sase-update",),
            duplicate_message=duplicate_message,
            on_complete=self._on_dev_update_complete,
        )

    def _submit_combined_update_proc(self, preview: DevUpdatePreview) -> None:
        """Run editable and managed legs as one tracked comprehensive proc."""
        assert preview.plan is not None
        plan = preview.plan

        def proc() -> TrackedProcResult[CombinedUpdateResult]:
            start = time.monotonic()
            dev_result = self._execute_dev_update(plan)
            append_dev_update_journal(plan, dev_result)
            if dev_update_failed(dev_result):
                reason = dev_update_failure_message(dev_result)
                return TrackedProcResult(
                    success=False,
                    message=reason,
                    error=reason,
                    payload=CombinedUpdateResult(
                        dev_result=dev_result,
                        managed_summary=None,
                        elapsed=max(0.0, time.monotonic() - start),
                    ),
                )

            try:
                managed_summary, _managed_elapsed = (
                    self._run_planned_sase_update_summary(
                        preview.managed_argv,
                        preview.managed_packages,
                    )
                )
            except UvToolError as exc:
                return TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                    payload=CombinedUpdateResult(
                        dev_result=dev_result,
                        managed_summary=None,
                        elapsed=max(0.0, time.monotonic() - start),
                    ),
                )

            result = CombinedUpdateResult(
                dev_result=dev_result,
                managed_summary=managed_summary,
                elapsed=max(0.0, time.monotonic() - start),
            )
            message = combined_sase_update_success_message(result)
            return TrackedProcResult(success=True, message=message, payload=result)

        submit = getattr(self.app, "_submit_session_worker", None)
        if submit is None:
            return
        submit(
            "sase-update",
            proc,
            display_name="sase update",
            cl_name="sase",
            dedup_key="sase-update",
            exclusive_scopes=("sase-update",),
            on_complete=self._on_combined_update_complete,
        )

    def _on_dev_update_complete(
        self, completion: TrackedProcCompletion[DevUpdateResult]
    ) -> None:
        """Toast/restart after an editable-checkout update proc."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="dev update failed",
        )

    def _on_combined_update_complete(
        self, completion: TrackedProcCompletion[CombinedUpdateResult]
    ) -> None:
        """Toast, receipt, and restart once for a comprehensive mixed update."""
        self._handle_code_update_completion(
            completion,
            failure_prefix="sase update failed",
            unchanged_message=SASE_UPDATE_NOOP_MESSAGE,
            unchanged_severity="error",
        )

    def _handle_code_update_completion(
        self,
        completion: TrackedProcCompletion[Any],
        *,
        failure_prefix: str,
        unchanged_message: str | None = None,
        unchanged_severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Common update completion handling: restart only after real changes."""
        if completion.success:
            if completion.payload is not None and managed_update_changed(
                completion.payload
            ):
                receipt = build_update_receipt(completion.payload)
                if receipt is not None:
                    write_pending_update_toast(receipt)
                self._restart_after_update(completion.message)
                return
            self._notify(
                unchanged_message or completion.message,
                severity=unchanged_severity,
            )
            if self.is_mounted and not self._loading:
                self._start_load(force=False)
        else:
            detail = completion.error or completion.message
            self._notify(f"{failure_prefix}: {detail}", severity="error")

    def _restart_after_update(self, message: str) -> None:
        """Notify briefly, then reuse the TUI + axe restart machinery."""
        self._restart_after_update_when_ready(message, deferred=False)

    def _restart_after_update_when_ready(self, message: str, *, deferred: bool) -> None:
        """Restart after tracked background procs have finished."""
        running_procs = running_background_procs(self.app)
        if running_procs:
            if not deferred:
                count = len(running_procs)
                noun = "proc" if count == 1 else "procs"
                verb = "finishes" if count == 1 else "finish"
                self._notify(f"{message} - restart queued until {count} {noun} {verb}.")
            set_timer = getattr(self.app, "set_timer", None)
            if callable(set_timer):
                set_timer(
                    1.0,
                    lambda: self._restart_after_update_when_ready(
                        message, deferred=True
                    ),
                )
            return

        self._notify(f"{message} — restarting ACE to load new code.")
        restart = getattr(self.app, "_restart_tui", None)
        if callable(restart):
            restart(restart_axe=True)


def running_background_procs(app: Any) -> list[Any]:
    """Return observed active procs that must finish before ACE can restart."""
    from sase.ace.tui.proc_observer import proc_projection_for

    return [
        proc
        for proc in proc_projection_for(app).rows
        if getattr(proc, "status", None) == "running"
    ]
