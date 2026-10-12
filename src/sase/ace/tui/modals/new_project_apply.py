"""Apply, init hand-off, and Ready/Failed glue for the New Project wizard."""

from __future__ import annotations

import asyncio
import subprocess
import threading
import weakref
from collections.abc import Mapping, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from textual.app import SuspendNotSupported

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.projects_pane_init import InitScope, init_cwd
from sase.ace.tui.modals.projects_pane_init_flow import (
    ProjectsInitHost,
    run_project_init,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.current_project import SetCurrentProjectOutcome, set_current_project
from sase.project_onboarding.preferences import (
    record_owner_selection,
    record_provider_selection,
    record_visibility_selection,
)
from sase.project_tags import ensure_project_tag_catalog

from .new_project_failed import NewProjectFailed
from .new_project_progress import NewProjectProgress
from .new_project_progress_model import ProgressResult
from .new_project_ready import NewProjectReady
from .new_project_review import NewProjectReview
from .new_project_review_model import ApplySubmission, strip_transport_flags
from .new_project_state import NewProjectStateMachine
from .project_selection_types import SelectionItem

if TYPE_CHECKING:
    from textual.app import App
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

_TASKS = "_new_project_modal_tasks"
_SET_CURRENT_NOTIFY_SEVERITY: dict[str, Literal["information", "warning", "error"]] = {
    "set": "information",
    "unchanged": "information",
    "ineligible": "warning",
    "unverified": "error",
}


def _terminal_apply_argv(argv: Sequence[str]) -> list[str]:
    """Return the Failed-stage terminal argv: ``--json`` removed, ``--yes`` kept.

    Option values equal to ``--json`` stay; only the transport flag is dropped.
    """
    stripped = strip_transport_flags(argv)
    stripped.append("--yes")
    return stripped


def _next_argv_requests_init(argv: Sequence[str]) -> bool:
    """Return whether *argv* is the init hand-off from a successful add."""
    tokens = [token for token in argv if token and token != "sase"]
    return bool(tokens) and tokens[0] == "init"


def _find_projects_pane(app: Any) -> Any | None:
    """Return the mounted Projects pane, if the Admin Center still hosts it."""
    query = getattr(app, "query", None)
    if not callable(query):
        return None
    try:
        from sase.ace.tui.modals.projects_pane import ProjectsPane

        for pane in query(ProjectsPane):
            if getattr(pane, "is_mounted", False):
                return pane
    except Exception:
        return None
    return None


def _reload_projects_if_mounted(app: Any) -> None:
    """Reload Projects when the pane is mounted, even if the wizard is gone."""
    pane = _find_projects_pane(app)
    reload = getattr(pane, "action_reload_projects", None)
    if callable(reload):
        reload()


def _on_project_add_complete(
    app: Any,
    modal_ref: weakref.ReferenceType[Any],
    completion: TrackedProcCompletion[Any],
) -> None:
    """Durable-add completion that outlives the wizard modal."""
    _on_project_apply_complete(app, modal_ref, {}, completion)


def _on_project_apply_complete(
    app: Any,
    modal_ref: weakref.ReferenceType[Any],
    intent: Mapping[str, str],
    completion: TrackedProcCompletion[Any],
) -> None:
    """Durable add/create completion that outlives the wizard modal."""
    _reload_projects_if_mounted(app)
    if completion.success and str(intent.get("mode") or "") == "create":
        _persist_create_preferences_async(intent)
    modal = modal_ref()
    observe = getattr(modal, "_observe_add_completion", None)
    if modal is not None and getattr(modal, "is_mounted", False) and callable(observe):
        observe(completion)


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
        "visibility": str(
            options.get("visibility") or creation.get("visibility") or ""
        ),
    }


def _record_successful_add_preferences(workflow_type: str, owner: str) -> None:
    """Persist last provider and owner after an ``ok`` add result."""
    if workflow_type:
        record_provider_selection(workflow_type)
    if workflow_type and owner:
        record_owner_selection(workflow_type, owner)


def _record_successful_create_preferences(
    workflow_type: str, owner: str, visibility: str
) -> None:
    """Persist provider, owner, and per-owner visibility after a successful create."""
    _record_successful_add_preferences(workflow_type, owner)
    if owner and visibility:
        record_visibility_selection(owner, visibility)


def _persist_create_preferences_async(intent: Mapping[str, str]) -> None:
    """Write create preferences off the UI thread; no open widget required."""
    thread = threading.Thread(
        target=_record_successful_create_preferences,
        args=(
            str(intent.get("workflow_type") or ""),
            str(intent.get("owner") or ""),
            str(intent.get("visibility") or ""),
        ),
        name="new-project-record-create-prefs",
        daemon=True,
    )
    thread.start()


class NewProjectInitHost:
    """Wizard adapter for :func:`run_project_init`."""

    def __init__(self, modal: Any) -> None:
        self._modal_ref = weakref.ref(modal)
        self._app = modal.app
        self._status = ""
        self._finished = False
        self._waiting_check = True
        self._awaiting_apply = False

    @property
    def app(self) -> Any:
        return self._app

    @property
    def is_mounted(self) -> bool:
        modal = self._modal_ref()
        if modal is not None and modal.is_mounted:
            return True
        pane = _find_projects_pane(self._app)
        return pane is not None and getattr(pane, "is_mounted", False)

    def push_screen(self, modal: Any, callback: Any) -> None:
        self._waiting_check = False

        def _wrapped(decision: Any) -> None:
            self._awaiting_apply = (
                decision is not None and getattr(decision, "action", None) == "apply"
            )
            callback(decision)

        self._app.push_screen(modal, _wrapped)

    def notify(self, message: str, **kwargs: Any) -> None:
        notify = getattr(self._app, "notify", None)
        if callable(notify):
            notify(message, **kwargs)

    def get_status(self) -> str:
        return self._status

    def set_status(self, message: str) -> None:
        self._status = message

    def suspend(self) -> Any:
        return self._app.suspend()

    def reload_projects(self) -> None:
        _reload_projects_if_mounted(self._app)

    def report_init_outcome(self, initialized: bool) -> None:
        self._finish(initialized)

    def recheck_after_terminal(self) -> bool:
        return True

    def _finish(self, initialized: bool) -> None:
        if self._finished:
            return
        self._finished = True
        modal = self._modal_ref()
        if modal is not None and modal.is_mounted:
            modal._on_init_finished(initialized)


class NewProjectApplyMixin(_MixinBase):
    """Submit durable add, tail Progress, and finish on Ready or Failed."""

    if TYPE_CHECKING:
        app: App[Any]
        is_mounted: bool
        _state: NewProjectStateMachine
        _apply_submission: ApplySubmission | None
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
        return app._submit_durable_proc(  # type: ignore[attr-defined]
            list(submission.argv),
            operation="project.add",
            request=submission.request,
            request_fingerprint=submission.request_fingerprint,
            concurrency_keys=list(submission.concurrency_keys),
            cwd=init_cwd(),
            display_name="Add project",
            cl_name=identity_key,
            on_complete=partial(_on_project_add_complete, app, modal_ref),
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
            on_complete=partial(_on_project_apply_complete, app, modal_ref, intent),
            on_handle=self._on_add_handle,
            reload_on_complete=False,
            duplicate_message="This repository is already being created.",
        )

    def _on_add_handle(self, old_id: str, new_id: str) -> None:
        if not self.is_mounted:
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
        log_path = getattr(presented, "log_path", "") or ""
        self.query_one(NewProjectProgress).attach_proc(proc_id, log_path=log_path)
        self.query_one(NewProjectProgress).focus()

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
        if result.status in {"ok", "partial"}:
            if result.status == "ok":
                spawn_pump_free_task(
                    self,
                    self._record_ok_preferences(),
                    name="new-project-record-owner",
                    registry_attr=_TASKS,
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
                _record_successful_create_preferences,
                intent["workflow_type"] or workflow_type,
                owner,
                intent["visibility"],
            )
            return
        await asyncio.to_thread(
            _record_successful_add_preferences, workflow_type, owner
        )

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
        if initialized:
            if self.is_mounted and self._state.stage == "progress":
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
        failed = self.query_one(NewProjectFailed)
        failed.show_failure(view, message=message)
        failed.focus()

    def _apply_ready_accent(self, accent: str) -> None:
        color = accent.strip() or "#00D7AF"
        frame = self.query_one("#new-project-frame")
        frame.styles.border = ("thick", color)
        title = self.query_one("#new-project-title")
        title.styles.color = color

    def _observe_add_completion(self, completion: TrackedProcCompletion[Any]) -> None:
        """Let Progress settle from proc evidence if NDJSON never arrived."""
        if not self.is_mounted or self._state.stage != "progress":
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
        hints = {
            "source": (
                "⏎ choose · [ ] provider · / filter · f forks · . all · "
                "R refresh · t provider login · esc close"
            ),
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
        from .new_project_modal import NewProjectSelection

        return NewProjectSelection(
            outcome,
            self._state.workflow_type,
            project_key=getattr(self, "_ready_key", ""),
        )

    def _dismiss_ready(self, outcome: str | None) -> None:
        result = None if outcome is None else self._show_outcome(outcome)
        self.dismiss(result)  # type: ignore[attr-defined]

    def _launch_from_ready(self) -> None:
        spawn_pump_free_task(
            self,
            self._ensure_catalog_and_launch(),
            name="new-project-plus-launch",
            registry_attr=_TASKS,
        )

    async def _ensure_catalog_and_launch(self) -> None:
        await asyncio.to_thread(ensure_project_tag_catalog)
        if not self.is_mounted:
            return
        key = getattr(self, "_ready_key", "")
        name = getattr(self, "_ready_name", "") or key
        selection = SelectionItem(
            display_name=name,
            item_type="project",
            project_name=key,
            cl_name=None,
            project_label=name or None,
        )
        app = self.app
        self._dismiss_center_underneath()
        self.dismiss(self._show_outcome("added"))  # type: ignore[attr-defined]
        starter = getattr(app, "_start_custom_agent_from_selection", None)
        if callable(starter):
            starter(selection)

    def _dismiss_center_underneath(self) -> None:
        try:
            from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
        except Exception:
            return
        for screen in getattr(self.app, "screen_stack", ()):
            if isinstance(screen, ConfigCenterModal):
                dismiss = getattr(screen, "dismiss", None)
                if callable(dismiss):
                    dismiss(None)
                return

    def _make_ready_current(self) -> None:
        key = getattr(self, "_ready_key", "")
        if not key:
            return
        spawn_pump_free_task(
            self,
            self._set_current_key(key),
            name="new-project-set-current",
            registry_attr=_TASKS,
        )

    async def _set_current_key(self, key: str) -> None:
        outcome = await asyncio.to_thread(set_current_project, key)
        if not self.is_mounted:
            return
        if not isinstance(outcome, SetCurrentProjectOutcome):
            self.notify("Could not set current project", severity="error")
            return
        self.notify(
            outcome.message,
            severity=_SET_CURRENT_NOTIFY_SEVERITY.get(outcome.status, "information"),
        )
        if outcome.status == "set":
            _reload_projects_if_mounted(self.app)

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


__all__ = [
    "NewProjectApplyMixin",
    "NewProjectInitHost",
]
