"""Completion delivery and worker-state routing for proc actions."""

from __future__ import annotations

import logging
from typing import Any

from textual.worker import Worker, WorkerState

from sase.project_display_names import humanize_cl_name, humanize_cl_names_in_text

from ..proc_observer import (
    ObservedProc,
    ProcCompletionRecord,
    ProcObserverSnapshot,
    ProcProjection,
)
from ._proc_action_submission import ProcSubmissionActionsMixin
from ._proc_action_types import (
    DurableSubmitWorkerResult,
    ProcCallbackConfig,
    SessionWorkerResult,
    TrackedProcCompletion,
    TrackedProcResult,
)

log = logging.getLogger(__name__)


class ProcCompletionActionsMixin(ProcSubmissionActionsMixin):
    """Deliver proc completions and route Textual worker state changes."""

    def _on_durable_submit_worker_completed(self, worker: Worker[Any]) -> None:
        """Register successful submit handles or surface submit failures."""
        result = worker.result
        if not isinstance(result, DurableSubmitWorkerResult):
            return
        placeholder_id = result.placeholder_id
        self._durable_submit_workers.pop(placeholder_id, None)
        self._proc_pending_scopes.pop(placeholder_id, None)
        observer = getattr(self, "_proc_observer", None)
        config = self._proc_completion_callbacks.get(placeholder_id)
        if result.handle is not None:
            if config is not None:
                self._proc_completion_callbacks[result.handle.proc_id] = config
                self._proc_completion_callbacks.pop(placeholder_id, None)
            if observer is not None:
                observer.register_submitted(
                    placeholder_id=placeholder_id,
                    proc_id=result.handle.proc_id,
                    operation=result.handle.operation,
                    result_path=result.handle.result_path,
                )
            return

        proc_result = result.result or TrackedProcResult(
            success=False,
            message="durable submit failed",
            error="durable submit failed",
        )
        proc_info = self._placeholder_proc(placeholder_id)
        if observer is not None:
            observer.remove_pending(placeholder_id)
        self._proc_completion_callbacks.pop(placeholder_id, None)
        self._deliver_tracked_completion(
            proc_id=placeholder_id,
            proc_info=proc_info,
            result=proc_result,
            output=proc_info.get_live_output(),
            config=config,
        )
        self._update_proc_indicator()

    def _on_durable_submit_worker_error(self, worker: Worker[Any]) -> None:
        """Handle a submit worker that raised before returning a typed result."""
        placeholder_id = next(
            (
                key
                for key, item in getattr(self, "_durable_submit_workers", {}).items()
                if item is worker
            ),
            None,
        )
        if placeholder_id is None:
            return
        self._durable_submit_workers.pop(placeholder_id, None)
        self._proc_pending_scopes.pop(placeholder_id, None)
        observer = getattr(self, "_proc_observer", None)
        if observer is not None:
            observer.remove_pending(placeholder_id)
        error_msg = str(worker.error) if worker.error else "Unknown submit error"
        config = self._proc_completion_callbacks.pop(placeholder_id, None)
        if config is not None:
            from ..durable_ops import release_workspace_claim

            release_workspace_claim(config.workspace_claim)
        proc_info = self._placeholder_proc(placeholder_id)
        self._deliver_tracked_completion(
            proc_id=placeholder_id,
            proc_info=proc_info,
            result=TrackedProcResult(
                success=False,
                message=error_msg,
                error=error_msg,
            ),
            output="",
            config=config,
        )
        self._update_proc_indicator()

    def _on_proc_observer_thread_snapshot(
        self,
        snapshot: ProcObserverSnapshot,
    ) -> None:
        """Receive an immutable snapshot from the observer thread."""
        try:
            self.call_from_thread(  # type: ignore[attr-defined]
                self._apply_proc_observer_snapshot, snapshot
            )
        except Exception:
            log.debug("proc observer snapshot delivery failed", exc_info=True)

    def _apply_proc_observer_snapshot(self, snapshot: ProcObserverSnapshot) -> None:
        """Apply observer projection and deliver decoded completions once."""
        self._proc_projection = snapshot.projection
        projection = self._effective_proc_projection()
        self._sync_proc_shell_agents_from_projection(projection)
        self._update_proc_indicator()
        for completion in snapshot.completions:
            self._deliver_observed_completion(completion, projection)

    def _sync_proc_shell_agents_from_projection(
        self,
        projection: ProcProjection | None = None,
    ) -> None:
        """Merge observer-cached proc-shell rows into the Agents-tab roster."""
        from ..models.agent_proc_shells import (
            merge_proc_shell_agents,
            proc_shell_agent_signature,
            proc_shell_agents_from_observed,
        )

        if projection is None:
            projection = self._effective_proc_projection()
        current_unfiltered = list(getattr(self, "_agents_with_children", []) or [])
        current_proc_shells = [
            agent for agent in current_unfiltered if agent.is_proc_shell
        ]
        proc_shells = proc_shell_agents_from_observed(projection.rows)
        if proc_shell_agent_signature(
            current_proc_shells
        ) == proc_shell_agent_signature(proc_shells):
            return

        previous_agents = list(getattr(self, "_agents", []) or [])
        self._agents_with_children = merge_proc_shell_agents(
            current_unfiltered,
            proc_shells,
        )
        self._agents = list(self._agents_with_children)
        invalidate = getattr(self, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            invalidate()

        on_agents_tab = getattr(self, "current_tab", None) == "agents"
        selected_identity = None
        current_idx = getattr(self, "current_idx", -1)
        if on_agents_tab and 0 <= current_idx < len(previous_agents):
            selected_identity = previous_agents[current_idx].identity
        elif not on_agents_tab:
            selected_identity = getattr(self, "_agents_last_identity", None)

        finalize = getattr(self, "_finalize_agent_list", None)
        if callable(finalize):
            finalize(
                on_agents_tab,
                selected_identity,
                save_unfiltered=False,
                previous_agents=previous_agents,
            )
        elif on_agents_tab:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)

    def _deliver_observed_completion(
        self,
        completion: ProcCompletionRecord,
        projection: ProcProjection,
    ) -> None:
        config = self._proc_completion_callbacks.pop(completion.proc_id, None)
        if config is None:
            return
        row = next(
            (
                item
                for item in projection.rows
                if item.proc_id == completion.proc_id
                or item.durable_proc_id == completion.proc_id
            ),
            None,
        ) or self._placeholder_proc(completion.proc_id)
        result: TrackedProcResult[Any]
        if completion.result is None:
            message = completion.error or "durable proc did not write a typed result"
            result = TrackedProcResult(
                success=False,
                message=message,
                error=message,
            )
        else:
            decoded = completion.result
            result = TrackedProcResult(
                success=decoded.success,
                message=decoded.message,
                payload=None if decoded.payload is None else dict(decoded.payload),
                error=decoded.error,
            )
        self._deliver_tracked_completion(
            proc_id=completion.proc_id,
            proc_info=row,
            result=result,
            output=row.get_live_output(),
            config=config,
        )

    def _deliver_tracked_completion(
        self,
        *,
        proc_id: str,
        proc_info: ObservedProc,
        result: TrackedProcResult[Any],
        output: str,
        config: ProcCallbackConfig | None,
    ) -> None:
        if config is None:
            config = ProcCallbackConfig(
                on_complete=None,
                reload_on_complete=True,
                notify_on_complete=True,
            )
        try:
            if config.notify_on_complete:
                self._notify_tracked_proc_result(proc_info, result)
            if config.on_complete is not None:
                config.on_complete(
                    TrackedProcCompletion(
                        proc_info=proc_info,
                        success=result.success,
                        message=result.message,
                        output=output,
                        payload=result.payload,
                        error=result.error,
                        collision=result.collision,
                    )
                )
            if config.reload_on_complete:
                self._reload_and_reposition()  # type: ignore[attr-defined]
        finally:
            if config.on_settled is not None:
                try:
                    config.on_settled()
                except Exception:
                    log.exception("Background proc %s settle callback failed", proc_id)
            self._update_proc_indicator()

    def _notify_tracked_proc_result(
        self,
        proc_info: ObservedProc,
        result: TrackedProcResult[Any],
    ) -> None:
        display_message = humanize_cl_names_in_text(result.message)
        if result.collision:
            self.notify(  # type: ignore[attr-defined]
                (
                    f"A {proc_info.proc_type} proc is already running for "
                    f"{humanize_cl_name(proc_info.cl_name)}"
                ),
                severity="warning",
            )
        elif result.success:
            self.notify(display_message)  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Proc failed: {display_message}",
                severity="error",
            )

    def _placeholder_proc(self, proc_id: str) -> ObservedProc:
        projection = self._effective_proc_projection()
        for row in projection.rows:
            if row.proc_id == proc_id or row.durable_proc_id == proc_id:
                return row
        from sase.core.time import local_now

        return ObservedProc(
            proc_id=proc_id,
            proc_type="proc",
            cl_name="",
            project_file="",
            status="error",
            message="proc failed",
            started_at=local_now(),
        )

    def _on_session_worker_completed(self, worker: Worker[Any]) -> None:
        """Deliver a session-local worker result on the UI thread."""
        result = worker.result
        if not isinstance(result, SessionWorkerResult):
            return
        callbacks = getattr(self, "_session_completion_callbacks", {})
        recorded = callbacks.pop(result.proc_id, None)
        workers = getattr(self, "_session_workers", {})
        workers.pop(result.proc_id, None)
        self._update_proc_indicator()
        if recorded is None:
            return
        on_complete, proc_info = recorded
        if on_complete is None:
            return
        proc_result = result.result
        on_complete(
            TrackedProcCompletion(
                proc_info=proc_info,
                success=proc_result.success,
                message=proc_result.message,
                output=result.output,
                payload=proc_result.payload,
                error=proc_result.error,
                collision=proc_result.collision,
            )
        )

    def _on_session_worker_error(self, worker: Worker[Any]) -> None:
        """Deliver a session-local worker error on the UI thread."""
        workers = getattr(self, "_session_workers", {})
        proc_id = next((key for key, item in workers.items() if item is worker), None)
        if proc_id is None:
            return
        workers.pop(proc_id, None)
        callbacks = getattr(self, "_session_completion_callbacks", {})
        recorded = callbacks.pop(proc_id, None)
        self._update_proc_indicator()
        if recorded is None:
            return
        on_complete, proc_info = recorded
        if on_complete is None:
            return
        error_msg = str(worker.error) if worker.error else "Unknown error"
        on_complete(
            TrackedProcCompletion(
                proc_info=proc_info,
                success=False,
                message=error_msg,
                output="",
                error=error_msg,
            )
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route worker state changes for proc submission and session workers."""
        if event.worker in getattr(self, "_durable_submit_workers", {}).values():
            if event.state == WorkerState.SUCCESS:
                self._on_durable_submit_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_durable_submit_worker_error(event.worker)
            return

        if event.worker in getattr(self, "_session_workers", {}).values():
            if event.state == WorkerState.SUCCESS:
                self._on_session_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_session_worker_error(event.worker)
            return

        axe_worker = getattr(self, "_axe_worker", None)
        if axe_worker is not None and event.worker is axe_worker:
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self._on_axe_worker_done(  # type: ignore[attr-defined]
                    event.worker, event.state
                )

        if event.worker is getattr(self, "_proc_reconciler_worker", None):
            if event.state in (
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            ):
                self._proc_reconciler_worker = None
                observer = getattr(self, "_proc_observer", None)
                if observer is not None:
                    observer.request_poll()
