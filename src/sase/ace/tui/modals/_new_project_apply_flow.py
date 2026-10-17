"""Apply, Progress, Ready, and Failed flow for the New Project wizard."""

from __future__ import annotations

import asyncio
import subprocess
import weakref
from collections.abc import Mapping, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from textual.app import SuspendNotSupported

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.projects_pane_init import InitScope, init_cwd
from sase.ace.tui.modals.projects_pane_init_flow import (
    ProjectsInitHost,
    run_project_init,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

from ._new_project_apply_init import NewProjectInitHost
from ._new_project_apply_ready import (
    dismiss_center_underneath,
    dismiss_ready,
    ensure_catalog_and_launch,
    launch_from_ready,
    make_ready_current,
    set_current_key,
    show_outcome,
)
from ._new_project_apply_shared import (
    on_project_add_complete,
    on_project_apply_complete,
    MODAL_TASKS,
    record_successful_add_preferences,
    record_successful_create_preferences,
    wizard_is_open,
)
from .new_project_failed import NewProjectFailed, create_setup_incomplete
from .new_project_progress import NewProjectProgress
from .new_project_progress_model import ProgressResult
from .new_project_ready import NewProjectReady
from .new_project_review import NewProjectReview
from .new_project_review_model import ApplySubmission, strip_transport_flags
from .new_project_state import NewProjectStateMachine
from .new_project_source import NewProjectSource
from .new_project_source_model import source_hint_line

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as MixinBase
else:
    MixinBase = object


def _terminal_apply_argv(argv: Sequence[str]) -> list[str]:
    """Return Failed-stage terminal argv with transport JSON removed and yes kept."""
    stripped = strip_transport_flags(argv)
    stripped.append("--yes")
    return stripped


def _next_argv_requests_init(argv: Sequence[str]) -> bool:
    """Return whether *argv* requests the init hand-off after a successful add."""
    tokens = [token for token in argv if token and token != "sase"]
    return bool(tokens) and tokens[0] == "init"


def _owner_from_target(target: Mapping[str, object]) -> str:
    owner = str(target.get("owner") or "")
    if owner:
        return owner
    ref = str(target.get("ref") or "")
    if "/" in ref:
        head = ref.split("/", 1)[0]
        return head.split(":")[-1]
    return ""


def _request_section(request: Mapping[str, Any], key: str) -> Mapping[str, object]:
    value = request.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _intent_from_submission(submission: ApplySubmission) -> dict[str, str]:
    request = submission.request
    target = _request_section(request, "target")
    options = _request_section(request, "options")
    creation = _request_section(request, "creation")
    return {
        "mode": str(request.get("mode") or "add"),
        "workflow_type": str(target.get("workflow_type") or ""),
        "owner": _owner_from_target(target),
        "project_key": submission.project_key,
        "visibility": str(
            options.get("visibility") or creation.get("visibility") or ""
        ),
    }


class NewProjectApplyMixin(MixinBase):
    """Submit durable add, tail Progress, and finish on Ready or Failed."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _apply_submission: ApplySubmission | None
        _apply_proc_id: str
        _progress_result: ProgressResult | None
        _init_host: NewProjectInitHost | None
        _local_plan: dict[str, object]
        _active_target: dict[str, object]
        _review_document: dict[str, object]
        _ready_key: str
        _ready_name: str
        _ready_accent: str
        _needs_init: bool

        def notify(self, message: str, **kwargs: Any) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _show_stage(self, stage: str) -> None: ...

    def _submit_project_add(self, submission: ApplySubmission) -> Any:
        """Register and submit the durable ``project.add`` proc."""
        app = self.app
        if not callable(getattr(app, "_submit_durable_proc", None)):
            self.notify("Project add queue is unavailable.", severity="error")
            return None
        identity_key = str(
            (submission.request.get("target") or {}).get("identity_key") or ""
        )
        modal_ref = weakref.ref(self)
        intent = _intent_from_submission(submission)
        return app._submit_durable_proc(  # type: ignore[attr-defined]
            list(submission.argv),
            operation="project.add",
            request=submission.request,
            request_fingerprint=submission.request_fingerprint,
            concurrency_keys=list(submission.concurrency_keys),
            cwd=init_cwd(),
            display_name="Add project",
            cl_name=identity_key,
            on_complete=partial(on_project_add_complete, app, modal_ref, intent),
            on_handle=self._on_add_handle,
            reload_on_complete=False,
            duplicate_message="This project is already being added.",
        )

    def _submit_project_create(self, submission: ApplySubmission) -> Any:
        """Register and submit the durable ``project.create`` proc."""
        app = self.app
        if not callable(getattr(app, "_submit_durable_proc", None)):
            self.notify("Project create queue is unavailable.", severity="error")
            return None
        identity_key = str(
            (submission.request.get("target") or {}).get("identity_key") or ""
        )
        modal_ref = weakref.ref(self)
        intent = _intent_from_submission(submission)
        return app._submit_durable_proc(  # type: ignore[attr-defined]
            list(submission.argv),
            operation="project.create",
            request=submission.request,
            request_fingerprint=submission.request_fingerprint,
            concurrency_keys=list(submission.concurrency_keys),
            cwd=init_cwd(),
            display_name="Create repository",
            cl_name=identity_key,
            on_complete=partial(on_project_apply_complete, app, modal_ref, intent),
            on_handle=self._on_add_handle,
            reload_on_complete=False,
            duplicate_message="This repository is already being created.",
        )

    def _on_add_handle(self, old_id: str, new_id: str) -> None:
        self._apply_proc_id = new_id or old_id or getattr(self, "_apply_proc_id", "")
        if not wizard_is_open(self):
            return
        self.query_one(NewProjectProgress).update_proc_id(old_id, new_id)

    def _start_apply(self, submission: ApplySubmission) -> None:
        self._apply_submission = submission
        if submission.operation == "project.create":
            presented = self._submit_project_create(submission)
        else:
            presented = self._submit_project_add(submission)
        if presented is None:
            return
        self._state.to_progress()
        self._show_stage("progress")
        proc_id = getattr(presented, "proc_id", "") or ""
        self._apply_proc_id = proc_id
        log_path = getattr(presented, "log_path", "") or ""
        progress = self.query_one(NewProjectProgress)
        progress.set_operation(submission.operation)
        progress.attach_proc(proc_id, log_path=log_path)
        progress.focus()

    def on_new_project_review_apply_requested(
        self, event: NewProjectReview.ApplyRequested
    ) -> None:
        review = self.query_one(NewProjectReview)
        self._review_document = dict(getattr(review, "_document", {}) or {})
        self._start_apply(event.submission)

    def on_new_project_progress_result_arrived(
        self, event: NewProjectProgress.ResultArrived
    ) -> None:
        self._on_progress_result(event.result)

    def on_new_project_ready_launch_requested(
        self, _event: NewProjectReady.LaunchRequested
    ) -> None:
        self._launch_from_ready()

    def on_new_project_ready_current_requested(
        self, _event: NewProjectReady.CurrentRequested
    ) -> None:
        self._make_ready_current()

    def on_new_project_ready_show_requested(
        self, _event: NewProjectReady.ShowRequested
    ) -> None:
        self._dismiss_ready("show")

    def on_new_project_ready_init_requested(
        self, _event: NewProjectReady.InitRequested
    ) -> None:
        result = self._progress_result
        if result is not None:
            self._state.to_progress()
            self._show_stage("progress")
            self._start_init_handoff(result)

    def on_new_project_failed_retry_requested(
        self, _event: NewProjectFailed.RetryRequested
    ) -> None:
        self._retry_review(recheck=True)

    def on_new_project_failed_terminal_requested(
        self, _event: NewProjectFailed.TerminalRequested
    ) -> None:
        self._run_failed_terminal()

    def on_new_project_failed_back_requested(
        self, _event: NewProjectFailed.BackRequested
    ) -> None:
        self._retry_review(recheck=False)

    def _on_progress_result(self, result: ProgressResult) -> None:
        if self._state.stage != "progress":
            return
        self._progress_result = result
        if result.status == "ok":
            spawn_pump_free_task(
                self,
                self._record_ok_preferences(),
                name="new-project-record-owner",
                registry_attr=MODAL_TASKS,
            )
            if _next_argv_requests_init(result.next_argv):
                self._start_init_handoff(result)
                return
            self._finish_ready(needs_init=False)
            return
        self._finish_failed()

    async def _record_ok_preferences(self) -> None:
        workflow_type = self._state.workflow_type
        owner = _owner_from_target(self._active_target)
        submission = self._apply_submission
        if submission is not None and submission.operation == "project.create":
            intent = _intent_from_submission(submission)
            owner = intent["owner"] or owner
            await asyncio.to_thread(
                record_successful_create_preferences,
                intent["workflow_type"] or workflow_type,
                owner,
                intent["visibility"],
            )
            return
        await asyncio.to_thread(record_successful_add_preferences, workflow_type, owner)

    def _start_init_handoff(self, result: ProgressResult) -> None:
        key = result.project_key
        name = result.project_name or key
        if not key:
            self._finish_ready(needs_init=False)
            return
        host = NewProjectInitHost(self)
        self._init_host = host
        protocol: ProjectsInitHost = host
        run_project_init(protocol, InitScope.for_projects([key], [name]))

    def _on_init_finished(self, initialized: bool) -> None:
        if not wizard_is_open(self) or self._state.stage != "progress":
            return
        if initialized:
            self.query_one(NewProjectProgress).mark_initialized()
            self._finish_ready(needs_init=False)
            return
        self._finish_ready(needs_init=True)

    def _finish_ready(self, *, needs_init: bool) -> None:
        result = self._progress_result
        key = result.project_key if result is not None else ""
        name = (result.project_name if result is not None else "") or key
        project = (
            self._local_plan.get("project")
            if isinstance(self._local_plan, dict)
            else None
        )
        accent = str(project.get("accent") or "") if isinstance(project, dict) else ""
        self._ready_key = key
        self._ready_name = name
        self._ready_accent = accent
        self._needs_init = needs_init
        self._state.finish_ready()
        self._show_stage("ready")
        ready = self.query_one(NewProjectReady)
        ready.show_project(name=name, key=key, accent=accent, needs_init=needs_init)
        ready.focus()
        self._apply_ready_accent(accent)

    def _finish_failed(self) -> None:
        self._state.finish_failed()
        self._show_stage("failed")
        view = self.query_one(NewProjectProgress).current_view()
        message = self._progress_result.message if self._progress_result else ""
        submission = self._apply_submission
        created_but_incomplete = (
            submission is not None
            and submission.operation == "project.create"
            and create_setup_incomplete(view)
        )
        registered_but_incomplete = (
            not created_but_incomplete
            and self._progress_result is not None
            and self._progress_result.status == "partial"
        )
        failed = self.query_one(NewProjectFailed)
        failed.show_failure(
            view,
            message=message,
            created_but_incomplete=created_but_incomplete,
            registered_but_incomplete=registered_but_incomplete,
        )
        failed.focus()

    def _apply_ready_accent(self, accent: str) -> None:
        color = accent.strip() or "#00D7AF"
        frame = self.query_one("#new-project-frame")
        frame.styles.border = ("thick", color)
        title = self.query_one("#new-project-title")
        title.styles.color = color

    def _observe_add_completion(self, completion: TrackedProcCompletion[Any]) -> None:
        """Let Progress settle from proc evidence if NDJSON never arrived."""
        if not wizard_is_open(self) or self._state.stage != "progress":
            return
        matches = self.query(NewProjectProgress)
        if not matches:
            return
        matches.first().observe_completion(completion)

    def _update_apply_chrome(self, stage: str) -> None:
        provider_row = self.query_one("#new-project-provider-row")
        provider_row.display = stage in {
            "source",
            "configure",
            "create-configure",
            "review",
        }
        try:
            hints_width = self.query_one("#new-project-hints").region.width
        except Exception:
            hints_width = 0
        try:
            app_width = self.app.size.width
        except Exception:
            app_width = 0
        width: int | None = hints_width or app_width or None
        matches = self.query(NewProjectSource)
        remedy = matches.first().remedy_advertised if matches else False
        hints = {
            "source": source_hint_line(width, remedy=remedy),
            "configure": (
                "tab fields · space setup · ctrl+s review · b back · esc close"
            ),
            "create-configure": (
                "tab fields · space toggle · a advanced · b back · esc close"
            ),
            "review": "y apply · b back · esc close",
            "progress": "esc close · setup continues in Procs",
            "ready": (
                "i initialize · + launch · c current · ⏎ show · esc close"
                if getattr(self, "_needs_init", False)
                else "+ launch · c current · ⏎ show · esc close"
            ),
            "failed": "r retry · t terminal · b back · esc close",
        }
        self.query_one("#new-project-hints").update(hints.get(stage, hints["source"]))

    def _show_outcome(self, outcome: str) -> Any:
        return show_outcome(self, outcome)

    def _dismiss_ready(self, outcome: str | None) -> None:
        dismiss_ready(self, outcome)

    def _launch_from_ready(self) -> None:
        launch_from_ready(self)

    async def _ensure_catalog_and_launch(self) -> None:
        await ensure_catalog_and_launch(self)

    def _dismiss_center_underneath(self) -> None:
        dismiss_center_underneath(self)

    def _make_ready_current(self) -> None:
        make_ready_current(self)

    async def _set_current_key(self, key: str) -> None:
        await set_current_key(self, key)

    def _retry_review(self, *, recheck: bool) -> None:
        self._state.back_to_review()
        self._show_stage("review")
        review = self.query_one(NewProjectReview)
        document = getattr(self, "_review_document", None) or self._local_plan
        if recheck:
            review.start_check(self._local_plan or document)
        else:
            review.show_document(document)
        review.query_one("#new-project-review-back").focus()

    def _run_failed_terminal(self) -> None:
        submission = self._apply_submission
        if submission is None:
            return
        argv = _terminal_apply_argv(submission.argv)
        cwd = str(init_cwd())
        try:
            with self.app.suspend():
                subprocess.run(argv, cwd=cwd, check=False)
        except (OSError, SuspendNotSupported) as exc:
            verb = (
                "create"
                if getattr(submission, "operation", "") == "project.create"
                else "add"
            )
            self.notify(f"Could not run {verb} in terminal: {exc}", severity="error")
            return
        self._retry_review(recheck=True)


__all__ = ["NewProjectApplyMixin"]
