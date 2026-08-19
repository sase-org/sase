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
from sase.ace.update_scope import UpdateScope
from sase.agent_clis.models import (
    AgentCliUpdateEntry,
    AgentCliUpdatesReady,
    UpdateStrategy,
)
from sase.agents_sync.models import CapturedIncomingHood
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
    captured = CapturedIncomingHood(
        project_key="alpha",
        project="Alpha",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id="alpha-foo",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine="zeus",
        top_hood="foo",
        hood_digest="b" * 64,
        run_count=1,
        family_count=1,
        cache_created_at=1.0,
    )
    return ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",), scope),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
        provider_plan=plan,
        agents_updates=(captured,),
    )


class _Harness(UpdateRunActionsMixin):
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.screens: list[object] = []
        self.callbacks: list[Any] = []
        self.messages: list[tuple[str, str]] = []
        self.restarts: list[str] = []
        self.updates_refreshes = 0
        self.agents_refreshes = 0
        self.agent_list_refreshes: list[str] = []
        self._automatic_update_status = None

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.messages.append((message, severity))

    def push_screen(self, screen: object, callback: object | None = None) -> None:
        self.screens.append(screen)
        self.callbacks.append(callback)

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object | None:
        assert_session_worker_submit_signature(args, kwargs)
        self.submitted = (args, kwargs)
        return None if self.reject else object()

    def _schedule_updates_indicator_revalidation(self) -> None:
        self.updates_refreshes += 1

    def _schedule_agents_sync_indicator_revalidation(self) -> None:
        self.agents_refreshes += 1

    def _schedule_agents_async_refresh(self, *, source: str) -> None:
        self.agent_list_refreshes.append(source)

    def _restart_after_update(self, message: str) -> None:
        self.restarts.append(message)


def test_preview_proc_runnable_result_pushes_confirm_modal() -> None:
    harness = _Harness()
    preview = _runnable_preview()

    harness._on_update_preview_complete(_completion(preview))

    assert len(harness.screens) == 1
    modal = harness.screens[0]
    assert isinstance(modal, PluginActionConfirmModal)
    assert modal._title == "Update everything"
    assert [section.title for section in modal._variants[0].sections] == [
        "SASE, core & plugins",
        "Agent CLIs",
        "Cached agent hoods",
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
            "sase + agent CLIs + cached hoods",
        ),
        (UpdateScope.SASE, "update SASE, core & plugins", "sase"),
        (UpdateScope.PROVIDERS, "update providers", "agent CLIs"),
        (UpdateScope.AGENTS, "import published agents", "cached hoods"),
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
        "agents-sync",
    )
    assert scoped_update_proc_names(scope) == (display_name, cl_name)


def test_duplicate_scoped_submission_is_rejected() -> None:
    harness = _Harness(reject=True)
    preview = _runnable_preview()

    assert harness._submit_scoped_update_task(preview) is False
    assert harness.submitted is not None
    _, kwargs = harness.submitted
    assert (
        kwargs["duplicate_message"]
        == "A SASE, agent CLI, or agents-repository update is already running."
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
        "sase.ace.tui.actions.update_run.build_update_receipt",
        lambda _result: receipt,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.update_run.write_pending_update_toast",
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
        "SASE, core & plugins: sase updated; Agent CLIs: no captured work; "
        "Cached agents: no cached agent hoods"
    ]
    assert harness.messages == []


def test_non_changing_result_toasts_without_restart() -> None:
    harness = _Harness()
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        )
    )

    harness._on_scoped_update_complete(_completion(result))

    assert harness.restarts == []
    assert harness.messages
    assert harness.messages[0][1] == "information"
    assert "already current" in harness.messages[0][0]


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
        "sase.ace.tui.actions.update_run.collect_update_preview_inputs",
        collect,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.update_run.build_comprehensive_update_preview",
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
