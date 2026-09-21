"""App-level update preview, confirmation, and scoped execution."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.actions.update_run import UpdateRunActionsMixin
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_execution import (
    scoped_preview_cl_name,
    scoped_update_proc_names,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.tui.proc_observer import ObservedProc
from sase.ace.tui.proc_observer import (
    ProcProjection,
    recount_projection,
    store_proc_row,
)
from sase.ace.update_scope import UpdateLeg, UpdateScope
from sase.agent_clis.models import (
    AgentCliUpdateEntry,
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
    UpdateStrategy,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN
from sase.procs import Proc
from tests.ace.tui._plugins_browser_pane_helpers import _agent_cli_statuses
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)


def _proc_info() -> ObservedProc:
    return ObservedProc(
        proc_id="session-0",
        proc_type="update-preview",
        cl_name="everything",
        project_file="",
        status="success",
        message="planned update",
        started_at=datetime(2026, 8, 19, 12, 0, 0),
    )


def _completion(
    payload: Any = None,
    *,
    success: bool = True,
    message: str = "ok",
    error: str | None = None,
) -> TrackedProcCompletion[Any]:
    return TrackedProcCompletion(
        proc_info=_proc_info(),
        success=success,
        message=message,
        output="",
        payload=payload,
        error=error,
    )


def _runnable_preview(
    scope: UpdateScope = UpdateScope.EVERYTHING,
    *,
    auto_approve: bool = False,
) -> ComprehensiveUpdatePreview:
    statuses = _agent_cli_statuses()
    claude = next(status for status in statuses if status.name == "claude")
    plan = AgentCliUpdatesReady(
        entries=(
            AgentCliUpdateEntry(
                status=claude,
                strategy=UpdateStrategy.SELF_UPDATE,
                argv=("claude", "update"),
            ),
        ),
        all_clis=False,
    )
    return ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(
            ("claude",), scope, auto_approve=auto_approve
        ),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
        provider_plan=plan,
    )


class _Harness(UpdateRunActionsMixin):
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.screens: list[object] = []
        self.callbacks: list[Any] = []
        self.messages: list[tuple[str, str]] = []
        self.notify_kwargs: list[dict[str, Any]] = []
        self.restarts: list[str] = []
        self.updates_refreshes = 0
        self._automatic_update_status = None

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **kwargs: Any,
    ) -> None:
        self.messages.append((message, severity))
        self.notify_kwargs.append(kwargs)

    def push_screen(self, screen: object, callback: object | None = None) -> None:
        self.screens.append(screen)
        self.callbacks.append(callback)

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object | None:
        assert_session_worker_submit_signature(args, kwargs)
        self.submitted = (args, kwargs)
        return None if self.reject else object()

    def _schedule_updates_indicator_revalidation(self) -> None:
        self.updates_refreshes += 1

    def _restart_after_update(self, message: str) -> None:
        self.restarts.append(message)


class _ProductionRestartHarness(_Harness):
    _restart_after_update = UpdateRunActionsMixin._restart_after_update

    def __init__(self, *procs: ObservedProc) -> None:
        super().__init__()
        self._proc_projection = recount_projection(ProcProjection(rows=procs))
        self.timer_callbacks: list[tuple[float, Any]] = []
        self.restart_axe_calls: list[bool] = []

    def set_timer(self, delay: float, callback: Any) -> object:
        self.timer_callbacks.append((delay, callback))
        return SimpleNamespace(stop=lambda: None)

    def _restart_tui(self, *, restart_axe: bool) -> None:
        self.restart_axe_calls.append(restart_axe)


def _telegram_receiver_row() -> ObservedProc:
    started_at = "2026-09-14T20:30:30.456885Z"
    return store_proc_row(
        Proc(
            proc_id="telegram-receiver",
            label="Telegram inbound long-poll receiver",
            kind="command",
            status="running",
            command=[],
            cwd="/tmp",
            origin="telegram-receiver",
            created_at=started_at,
            started_at=started_at,
            log_path="/tmp/telegram-receiver.log",
            message="polling",
        )
    )


def _monitor_shell_row() -> ObservedProc:
    row = _telegram_receiver_row()
    row.origin = MONITOR_PROC_ORIGIN
    row.proc_id = "monitor-shell"
    row.display_name = "SASE monitor"
    return row


def test_preview_proc_runnable_result_pushes_confirm_modal() -> None:
    harness = _Harness()
    preview = _runnable_preview()

    harness._on_update_preview_complete(_completion(preview))

    assert harness.submitted is None
    assert len(harness.screens) == 1
    modal = harness.screens[0]
    assert isinstance(modal, PluginActionConfirmModal)
    assert modal._title == "Update everything"
    assert [section.title for section in modal._variants[0].sections] == [
        "SASE, core & plugins",
        "Agent CLIs",
    ]


def test_preview_proc_non_runnable_result_toasts_instead() -> None:
    harness = _Harness()
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE),
        sase_preview=None,
        sase_current=True,
    )

    harness._on_update_preview_complete(_completion(preview))

    assert harness.screens == []
    assert harness.messages == [
        (
            "SASE, core, and plugins in the captured update are already current.",
            "information",
        )
    ]


def test_preview_proc_none_payload_toasts_error() -> None:
    harness = _Harness()

    harness._on_update_preview_complete(
        _completion(None, success=False, message="boom", error="boom")
    )

    assert harness.screens == []
    assert harness.messages == [("update preview failed: boom", "error")]


@pytest.mark.parametrize(
    ("scope", "display_name", "cl_name"),
    [
        (
            UpdateScope.EVERYTHING,
            "comprehensive update",
            "sase + agent CLIs",
        ),
        (UpdateScope.SASE, "update SASE, core & plugins", "sase"),
        (UpdateScope.PROVIDERS, "update providers", "agent CLIs"),
    ],
)
def test_confirmed_modal_submits_scoped_mutation_proc(
    scope: UpdateScope,
    display_name: str,
    cl_name: str,
) -> None:
    harness = _Harness()
    preview = _runnable_preview(scope)
    harness._on_update_preview_complete(_completion(preview))
    callback = harness.callbacks[0]
    assert callable(callback)

    callback(PluginActionConfirmResult(variant_key="comprehensive-update"))

    assert harness.submitted is not None
    args, kwargs = harness.submitted
    assert args[0] == "comprehensive-update"
    assert kwargs["display_name"] == display_name
    assert kwargs["cl_name"] == cl_name
    assert kwargs["dedup_key"] == "comprehensive-update"
    assert kwargs["exclusive_scopes"] == (
        "sase-update",
        "agent-cli-update",
    )
    assert scoped_update_proc_names(scope) == (display_name, cl_name)


@pytest.mark.parametrize(
    ("scope", "display_name", "cl_name"),
    [
        (
            UpdateScope.EVERYTHING,
            "comprehensive update",
            "sase + agent CLIs",
        ),
        (UpdateScope.SASE, "update SASE, core & plugins", "sase"),
        (UpdateScope.PROVIDERS, "update providers", "agent CLIs"),
    ],
)
def test_auto_approved_runnable_preview_submits_without_confirm(
    scope: UpdateScope,
    display_name: str,
    cl_name: str,
) -> None:
    harness = _Harness()
    preview = _runnable_preview(scope, auto_approve=True)

    harness._on_update_preview_complete(_completion(preview))

    assert harness.screens == []
    assert harness.callbacks == []
    assert harness.submitted is not None
    args, kwargs = harness.submitted
    assert args[0] == "comprehensive-update"
    assert kwargs["display_name"] == display_name
    assert kwargs["cl_name"] == cl_name
    assert kwargs["dedup_key"] == "comprehensive-update"
    assert kwargs["exclusive_scopes"] == (
        "sase-update",
        "agent-cli-update",
    )
    assert scoped_update_proc_names(scope) == (display_name, cl_name)


def test_auto_approved_non_runnable_preview_does_not_mutate() -> None:
    harness = _Harness()
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE, auto_approve=True),
        sase_preview=None,
        sase_current=True,
    )

    harness._on_update_preview_complete(_completion(preview))

    assert harness.screens == []
    assert harness.submitted is None
    assert harness.messages == [
        (
            "SASE, core, and plugins in the captured update are already current.",
            "information",
        )
    ]


def test_auto_approved_preview_error_does_not_mutate() -> None:
    harness = _Harness()

    harness._on_update_preview_complete(
        _completion(None, success=False, message="boom", error="boom")
    )

    assert harness.screens == []
    assert harness.submitted is None
    assert harness.messages == [("update preview failed: boom", "error")]


def test_duplicate_scoped_submission_is_rejected() -> None:
    harness = _Harness(reject=True)
    preview = _runnable_preview()

    assert harness._submit_scoped_update_task(preview) is False
    assert harness.submitted is not None
    _, kwargs = harness.submitted
    assert (
        kwargs["duplicate_message"] == "A SASE or agent CLI update is already running."
    )


def test_duplicate_preview_submission_is_rejected() -> None:
    harness = _Harness(reject=True)

    assert (
        harness._submit_update_preview_proc(
            ComprehensiveUpdateRequest((), UpdateScope.PROVIDERS)
        )
        is False
    )
    assert harness.submitted is not None
    args, kwargs = harness.submitted
    assert args[0] == "update-preview"
    assert kwargs["display_name"] == "plan update"
    assert kwargs["cl_name"] == scoped_preview_cl_name(UpdateScope.PROVIDERS)
    assert kwargs["dedup_key"] == "update-preview"
    assert kwargs["exclusive_scopes"] == ()
    assert kwargs["duplicate_message"] == "An update is already being planned."


def test_code_changed_result_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[object] = []
    receipt = object()
    monkeypatch.setattr(
        "sase.ace.update_receipt.build_update_receipt",
        lambda _result: receipt,
    )
    monkeypatch.setattr(
        "sase.ace.update_receipt.write_pending_update_toast",
        written.append,
    )
    harness = _Harness()
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.UPDATED,
            "sase updated",
            SimpleNamespace(changed=True),
        )
    )

    harness._on_scoped_update_complete(_completion(result, message="sase updated"))

    assert written == [receipt]
    assert harness.restarts == [
        "SASE, core & plugins: sase updated; Agent CLIs: no captured work"
    ]
    assert harness.messages == []


def test_code_changed_result_restarts_immediately_with_monitor_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[object] = []
    receipt = object()
    monkeypatch.setattr(
        "sase.ace.update_receipt.build_update_receipt",
        lambda _result: receipt,
    )
    monkeypatch.setattr(
        "sase.ace.update_receipt.write_pending_update_toast",
        written.append,
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    harness = _ProductionRestartHarness(_monitor_shell_row())
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.UPDATED,
            "sase updated",
            SimpleNamespace(changed=True),
        )
    )

    harness._on_scoped_update_complete(_completion(result, message="sase updated"))

    assert written == [receipt]
    assert harness.restart_axe_calls == [True]
    assert harness.timer_callbacks == []
    assert harness.messages == [
        (
            "SASE, core & plugins: sase updated; Agent CLIs: no captured work "
            "— restarting ACE to load new code.",
            "information",
        )
    ]


def test_code_changed_result_waits_for_telegram_receiver_like_ordinary_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[object] = []
    receipt = object()
    monkeypatch.setattr(
        "sase.ace.update_receipt.build_update_receipt",
        lambda _result: receipt,
    )
    monkeypatch.setattr(
        "sase.ace.update_receipt.write_pending_update_toast",
        written.append,
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    harness = _ProductionRestartHarness(_telegram_receiver_row())
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.UPDATED,
            "sase updated",
            SimpleNamespace(changed=True),
        )
    )

    harness._on_scoped_update_complete(_completion(result, message="sase updated"))

    assert written == [receipt]
    assert harness.restart_axe_calls == []
    assert len(harness.timer_callbacks) == 1
    assert harness.messages == [
        (
            "SASE, core & plugins: sase updated; Agent CLIs: no captured work "
            "- restart queued until 1 proc finishes.",
            "information",
        )
    ]


def test_non_changing_result_toasts_without_restart() -> None:
    harness = _Harness()
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        ),
    )

    harness._on_scoped_update_complete(_completion(result))

    assert harness.restarts == []
    assert harness.messages
    assert harness.messages[0][1] == "information"
    assert "already current" in harness.messages[0][0]
    assert harness.updates_refreshes == 1


def test_providers_only_result_raises_rich_completion_toast() -> None:
    harness = _Harness()
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.SKIPPED,
            "not selected",
        ),
        provider_results=(
            AgentCliUpdateResult(
                name="claude",
                display_name="Claude Code",
                status=UpdateResultStatus.UPDATED,
                old_version="2.1.0",
                new_version="2.2.0",
                command=None,
                docs_url=None,
            ),
        ),
        selected_legs=frozenset({UpdateLeg.PROVIDERS}),
    )

    harness._on_scoped_update_complete(_completion(result))

    assert harness.restarts == []
    assert harness.messages == [
        (
            "[bold]Agent CLIs[/]\n• Claude Code: [dim]2.1.0 →[/] [green]2.2.0[/]",
            "information",
        )
    ]
    assert harness.notify_kwargs == [
        {"title": "✓ Providers updated", "markup": True, "timeout": 10.0}
    ]


def test_notify_forwards_only_supplied_arguments() -> None:
    harness = _Harness()

    harness._notify("plain", severity="warning")
    harness._notify("rich", title="T", markup=True, timeout=3.0)

    assert harness.messages == [("plain", "warning"), ("rich", "information")]
    assert harness.notify_kwargs == [
        {},
        {"title": "T", "markup": True, "timeout": 3.0},
    ]


def test_preview_proc_body_collects_inputs_then_builds_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collected: list[object] = []
    preview = _runnable_preview(UpdateScope.SASE)

    def collect(*, cached_status: object, legs: object) -> object:
        collected.append((cached_status, frozenset(legs)))
        return SimpleNamespace(name="inputs")

    def build(request: ComprehensiveUpdateRequest, inputs: object) -> object:
        collected.append((request.scope, getattr(inputs, "name", None)))
        return preview

    monkeypatch.setattr(
        "sase.ace.tui.update_preview_inputs.collect_update_preview_inputs",
        collect,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_preview.build_comprehensive_update_preview",
        build,
    )
    harness = _Harness()
    status = object()
    harness._automatic_update_status = status  # type: ignore[assignment]

    assert harness._submit_update_preview_proc(
        ComprehensiveUpdateRequest((), UpdateScope.SASE)
    )
    assert harness.submitted is not None
    task_result = harness.submitted[0][1]()
    assert isinstance(task_result, TrackedProcResult)
    assert task_result.payload is preview
    assert collected[0] == (status, preview.selected_legs)
    assert collected[1] == (UpdateScope.SASE, "inputs")
