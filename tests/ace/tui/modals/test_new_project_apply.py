"""Apply, Progress, Ready, and Failed coverage for the New Project wizard."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
import weakref

import pytest
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.new_project_apply import (
    _next_argv_requests_init,
    _on_project_add_complete,
    _reload_projects_if_mounted,
    _terminal_apply_argv,
)
from sase.ace.tui.modals.new_project_failed import NewProjectFailed
from sase.ace.tui.modals.new_project_modal import NewProjectModal, NewProjectSelection
from sase.ace.tui.modals.new_project_progress import (
    NewProjectProgress,
    format_elapsed,
    _render_raw_log,
)
from sase.ace.tui.modals.new_project_progress_model import (
    ProgressResult,
    ProgressView,
    reduce_lines,
)
from sase.ace.tui.modals.new_project_ready import NewProjectReady
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.modals.new_project_review_model import apply_submission
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now
from tests.ace.tui.modals.test_new_project_configure_review import (
    _WizardApp,
    _document,
    _make_add_flow,
    _select_suggested,
    _tab_to_review,
)


def _proc() -> ObservedProc:
    return ObservedProc(
        proc_id="add-1",
        proc_type="project.add",
        cl_name="",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
    )


def _result(
    status: str = "ok",
    *,
    next_argv: tuple[str, ...] = (),
    key: str = "gh_sase-org__new",
    message: str = "added",
) -> ProgressResult:
    return ProgressResult(
        status=status,  # type: ignore[arg-type]
        project_key=key,
        project_name="new",
        next_argv=next_argv,
        message=message,
    )


def _mid_run_view() -> ProgressView:
    return reduce_lines(
        [
            '{"event":"plan","plan":{"steps":['
            '{"id":"checkout","label":"Clone and register","state":"pending"},'
            '{"id":"manage","label":"Mark as SASE-managed","state":"pending"}]}}',
            '{"event":"step","id":"checkout","status":"running"}',
        ]
    )


def _failed_view() -> ProgressView:
    return reduce_lines(
        [
            '{"event":"plan","plan":{"steps":['
            '{"id":"checkout","label":"Clone and register","state":"pending"}]}}',
            '{"event":"step","id":"checkout","status":"failed",'
            '"message":"Could not clone",'
            '"hint":"The repository was kept. Re-run the same command to retry."}',
            '{"event":"result","status":"failed","project":{"key":"k","name":"n"},'
            '"message":"Could not clone"}',
        ]
    )


async def _open_review(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any, NewProjectModal]:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    return app, modal, modal


async def _confirm_review(pilot: Any, modal: NewProjectModal) -> None:
    await _tab_to_review(pilot, modal)
    await pilot.press("enter")
    await pilot.pause()
    await pilot.press("y")
    await pilot.pause()


def test_terminal_apply_argv_strips_json_keeps_yes() -> None:
    argv = ["sase", "project", "add", "sase-org/new", "--yes", "--json"]
    assert _terminal_apply_argv(argv) == [
        "sase",
        "project",
        "add",
        "sase-org/new",
        "--yes",
    ]
    assert _next_argv_requests_init(("sase", "init", "-p", "k"))
    assert not _next_argv_requests_init(("sase", "project", "show", "k"))


async def test_y_submits_apply_submission_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal, _ = await _open_review(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        assert modal._state.stage == "progress"
        assert app.submit_calls
        argv, kwargs = app.submit_calls[0]
        expected = apply_submission(_document("new"))
        assert argv == list(expected.argv)
        assert kwargs["operation"] == "project.add"
        assert kwargs["request"] == expected.request
        assert kwargs["request_fingerprint"] == expected.request_fingerprint
        assert kwargs["concurrency_keys"] == list(expected.concurrency_keys)
        assert kwargs["reload_on_complete"] is False


async def test_duplicate_concurrency_key_stays_on_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal, _ = await _open_review(monkeypatch)
    app.submit_result = None
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        assert modal._state.stage == "review"
        assert modal._apply_submission == apply_submission(_document("new"))


async def test_dismiss_during_run_still_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reloads: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._reload_projects_if_mounted",
        lambda app: reloads.append(app),
    )
    app, modal, _ = await _open_review(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        assert modal._state.stage == "progress"
        on_complete = app.submit_calls[0][1]["on_complete"]
        modal.dismiss(None)
        await pilot.pause()
        on_complete(
            TrackedProcCompletion(
                proc_info=_proc(),
                success=True,
                message="added",
                output="",
            )
        )
        assert reloads == [app]


async def test_ok_without_init_goes_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    app, modal, _ = await _open_review(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        modal._on_progress_result(_result("ok"))
        await pilot.pause()
        assert modal._state.stage == "ready"
        ready = modal.query_one(NewProjectReady)
        assert "new" in ready.query_one("#new-project-ready-name").render().plain
        assert not ready._needs_init


async def test_ok_with_init_handoff_then_cancelled_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes: list[Any] = []

    def fake_init(host: Any, scope: Any) -> Any:
        scopes.append(scope)
        host._finish(False)
        return None

    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply.run_project_init",
        fake_init,
    )
    app, modal, _ = await _open_review(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        modal._on_progress_result(
            _result("ok", next_argv=("sase", "init", "-p", "gh_sase-org__new"))
        )
        await pilot.pause()
        assert scopes
        assert modal._state.stage == "ready"
        ready = modal.query_one(NewProjectReady)
        assert ready._needs_init
        assert (
            "Not initialized"
            in ready.query_one("#new-project-ready-init").render().plain
        )


async def test_failed_keeps_checklist_and_t_strips_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[Any] = []

    class _Suspend:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply.subprocess.run",
        lambda argv, **kwargs: runs.append((argv, kwargs)),
    )
    app, modal, _ = await _open_review(monkeypatch)
    app.suspend = lambda: _Suspend()  # type: ignore[method-assign]
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        progress = modal.query_one(NewProjectProgress)
        progress.show_preview(_failed_view())
        modal._on_progress_result(_result("failed", message="Could not clone"))
        await pilot.pause()
        assert modal._state.stage == "failed"
        failed = modal.query_one(NewProjectFailed)
        body = failed.query_one("#new-project-failed-message").render().plain
        assert "repository was kept" in body
        await pilot.press("t")
        await pilot.pause()
        assert runs
        argv, kwargs = runs[0]
        assert "--json" not in argv
        assert "--yes" in argv
        assert modal._state.stage == "review"


async def test_ready_enter_dismisses_with_show_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal, _ = await _open_review(monkeypatch)
    dismissed: list[object] = []
    original = modal.dismiss

    def capture(result: object = None) -> None:
        dismissed.append(result)
        original(result)

    modal.dismiss = capture  # type: ignore[method-assign]
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _confirm_review(pilot, modal)
        modal._on_progress_result(_result("ok"))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert dismissed
        result = dismissed[-1]
        assert isinstance(result, NewProjectSelection)
        assert result.outcome == "show"
        assert result.project_key == "gh_sase-org__new"


def test_reload_projects_if_mounted_calls_pane_action() -> None:
    pane = MagicMock()
    pane.is_mounted = True
    app = MagicMock()
    app.query.return_value = [pane]
    _reload_projects_if_mounted(app)
    pane.action_reload_projects.assert_called_once()


def test_on_project_add_complete_reloads(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._reload_projects_if_mounted",
        lambda app: called.append(app),
    )

    class _Gone:
        is_mounted = False

    app = object()
    _on_project_add_complete(
        app,
        weakref.ref(_Gone()),
        TrackedProcCompletion(proc_info=_proc(), success=True, message="ok", output=""),
    )
    assert called == [app]


def test_mark_sase_initialized_appends_done_row() -> None:
    view = _mid_run_view()
    view.mark_sase_initialized()
    assert view.steps["sase-init"].state == "done"
    assert view.steps["sase-init"].label == "SASE initialized"


async def test_configure_and_review_hints_and_completed_stepper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal, _ = await _open_review(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        hints = modal.query_one("#new-project-hints").render().plain
        assert "ctrl+s review" in hints
        assert "[ ] provider" not in hints
        await _tab_to_review(pilot, modal)
        await pilot.press("enter")
        await pilot.pause()
        hints = modal.query_one("#new-project-hints").render().plain
        assert "y apply" in hints
        stepper = modal.query_one("#new-project-stepper").render().plain
        assert "● Review" in stepper
        await pilot.press("y")
        await pilot.pause()
        stepper = modal.query_one("#new-project-stepper").render().plain
        assert "✓ Review" in stepper
        assert "● Review" not in stepper
        modal._cycle_provider(1)
        assert modal._state.workflow_type == "gh"


def test_format_elapsed_and_raw_log_disclosure() -> None:
    assert format_elapsed(3) == "3s"
    assert format_elapsed(75) == "1m 15s"
    collapsed = _render_raw_log(["one", "two"], expanded=False)
    assert "▸ raw log (2 lines)" in collapsed.plain
    assert "one" not in collapsed.plain
    expanded = _render_raw_log(["one", "two"], expanded=True)
    assert "▾ raw log (2 lines)" in expanded.plain
    assert "two" in expanded.plain
