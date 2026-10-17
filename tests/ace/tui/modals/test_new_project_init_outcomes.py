"""Wizard init host reports verified controller outcomes only."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.modals.new_project_apply import NewProjectInitHost
from sase.ace.tui.modals.new_project_ready import NewProjectReady
from sase.ace.tui.modals.projects_pane_init import InitScope
from sase.ace.tui.modals.projects_pane_init_flow import ProjectsInitFlowController
from sase.ace.tui.modals.projects_pane_init_payload import InitCheckPayload
from tests.ace.tui._projects_pane_init_flow_helpers import (
    _completion,
    _tty_blocked_payload,
)
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    check_payload,
    project_plan,
)
from sase.ace.tui.modals.new_project_review import NewProjectReview
from tests.ace.tui.modals.test_new_project_apply import _result
from tests.ace.tui.modals.test_new_project_configure_review import (
    _make_add_flow,
    _select_suggested,
    _tab_to_review,
)


class _Host:
    def __init__(self) -> None:
        self.app = SimpleNamespace()
        self.is_mounted = True
        self.status = ""
        self.notices: list[tuple[str, str]] = []
        self.reloads = 0
        self.outcomes: list[bool] = []
        self.screens: list[Any] = []
        self.recheck = True
        self.suspend_impl = lambda: _Suspend()

    def push_screen(self, modal: Any, callback: Any) -> None:
        self.screens.append((modal, callback))

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notices.append((message, str(kwargs.get("severity") or "information")))

    def get_status(self) -> str:
        return self.status

    def set_status(self, message: str) -> None:
        self.status = message

    def suspend(self) -> Any:
        return self.suspend_impl()

    def reload_projects(self) -> None:
        self.reloads += 1

    def report_init_outcome(self, initialized: bool) -> None:
        self.outcomes.append(initialized)

    def recheck_after_terminal(self) -> bool:
        return self.recheck


class _Suspend:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> None:
        return None


def _install_submit(host: _Host) -> list[tuple[Any, dict[str, Any], Any]]:
    submitted: list[tuple[Any, dict[str, Any], Any]] = []

    def fake_submit(*args: Any, **kwargs: Any) -> Any:
        handle = SimpleNamespace(proc_id=f"session-{len(submitted)}")
        submitted.append((args, kwargs, handle))
        return handle

    host.app._submit_session_worker = fake_submit  # type: ignore[attr-defined]
    return submitted


def test_current_check_reports_initialized() -> None:
    host = _Host()
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    flow.start_init_check(InitScope.for_projects(["alpha"], ["alpha"]))
    _args, kwargs, handle = submitted[0]
    payload: InitCheckPayload = check_payload(project_plan("alpha"), status="current")
    kwargs["on_complete"](_completion(handle.proc_id, payload))
    assert host.outcomes == [True]
    assert host.reloads == 0


def test_cancelled_preview_reports_not_initialized() -> None:
    host = _Host()
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    flow.start_init_check(InitScope.for_projects(["alpha"], ["alpha"]))
    _args, kwargs, handle = submitted[0]
    payload = check_payload(project_plan("alpha", status="needs_attention"))
    kwargs["on_complete"](_completion(handle.proc_id, payload))
    _modal, callback = host.screens[0]
    callback(None)
    assert host.outcomes == [False]


def test_failed_check_reports_not_initialized() -> None:
    host = _Host()
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    flow.start_init_check(InitScope.for_projects(["alpha"], ["alpha"]))
    _args, kwargs, handle = submitted[0]
    kwargs["on_complete"](
        _completion(handle.proc_id, None, success=False, message="boom", error="boom")
    )
    assert host.outcomes == [False]


def test_terminal_nonzero_skips_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _Host()
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_flow.subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(["sase"], 1, "", ""),
    )
    flow._run_init_in_terminal(_tty_blocked_payload("alpha"))
    assert host.outcomes == [False]
    assert len(submitted) == 0


def test_terminal_zero_rechecks_same_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _Host()
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_flow.subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(["sase"], 0, "", ""),
    )
    flow._run_init_in_terminal(_tty_blocked_payload("alpha"))
    assert len(submitted) == 1
    assert host.outcomes == []


def test_pane_terminal_does_not_recheck(monkeypatch: pytest.MonkeyPatch) -> None:
    host = _Host()
    host.recheck = False
    submitted = _install_submit(host)
    flow = ProjectsInitFlowController(host)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane_init_flow.subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess(["sase"], 0, "", ""),
    )
    flow._run_init_in_terminal(_tty_blocked_payload("alpha"))
    assert len(submitted) == 0
    assert host.reloads == 1
    assert host.outcomes == []


def test_reload_does_not_finish_wizard_host() -> None:
    finished: list[bool] = []

    class _Modal:
        is_mounted = True
        app = SimpleNamespace()

        def _on_init_finished(self, initialized: bool) -> None:
            finished.append(initialized)

    modal = _Modal()
    modal.app = SimpleNamespace(screen_stack=[modal])
    host = NewProjectInitHost(modal)
    host.reload_projects()
    assert finished == []
    host.report_init_outcome(True)
    assert finished == [True]


def test_closed_wizard_host_drops_outcome() -> None:
    finished: list[bool] = []

    class _Modal:
        is_mounted = True
        app = SimpleNamespace(screen_stack=[])

        def _on_init_finished(self, initialized: bool) -> None:
            finished.append(initialized)

    host = NewProjectInitHost(_Modal())
    assert host.is_mounted is False
    host.report_init_outcome(False)
    assert finished == []


async def _start_wizard_init_handoff(
    pilot: Any, app: Any, modal: Any
) -> list[tuple[tuple[Any, ...], dict[str, Any], Any]]:
    submitted: list[tuple[tuple[Any, ...], dict[str, Any], Any]] = []

    def fake_submit(*args: Any, **kwargs: Any) -> Any:
        handle = SimpleNamespace(proc_id=f"session-{len(submitted)}")
        submitted.append((args, kwargs, handle))
        return handle

    app._submit_session_worker = fake_submit  # type: ignore[method-assign]
    app.push_screen(modal)
    await pilot.pause()
    _select_suggested(modal)
    await pilot.pause()
    await _tab_to_review(pilot, modal)
    await pilot.press("enter")
    await pilot.pause()
    await pilot.press("y")
    await pilot.pause()
    modal._on_progress_result(
        _result("ok", next_argv=("sase", "init", "-p", "gh_sase-org__new"))
    )
    await pilot.pause()
    assert submitted
    return submitted


async def test_wizard_init_success_marks_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        submitted = await _start_wizard_init_handoff(pilot, app, modal)
        _args, kwargs, handle = submitted[0]
        payload = check_payload(project_plan("gh_sase-org__new"), status="current")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await pilot.pause()
        assert modal._state.stage == "ready"
        ready = modal.query_one(NewProjectReady)
        assert not ready._needs_init


@pytest.mark.parametrize("outcome", ["failed", "current"])
async def test_closed_wizard_ignores_late_init_outcome(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        submitted = await _start_wizard_init_handoff(pilot, app, modal)
        _args, kwargs, handle = submitted[0]
        if outcome == "failed":
            completion = _completion(
                handle.proc_id, None, success=False, message="boom", error="boom"
            )
        else:
            payload = check_payload(project_plan("gh_sase-org__new"), status="current")
            completion = _completion(handle.proc_id, payload)

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert modal not in app.screen_stack
        kwargs["on_complete"](completion)
        await pilot.pause()
        assert modal._state.stage == "progress"
