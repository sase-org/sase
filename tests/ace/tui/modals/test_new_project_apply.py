"""Apply, Progress, Ready, and Failed coverage for the New Project wizard."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
import weakref

import pytest
from sase import workspace_provider
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.new_project_apply import (
    _find_projects_pane,
    _intent_from_submission,
    _next_argv_requests_init,
    _on_project_add_complete,
    _reload_projects_if_mounted,
    _terminal_apply_argv,
)
from sase.ace.tui.modals.new_project_failed import (
    NewProjectFailed,
    create_setup_incomplete,
)
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
        assert expected.project_key == "gh_sase-org__new"


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
        workspace_provider, "describe_repo_creation", lambda *_args, **_kwargs: None
    )
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
        terminal = [
            argv
            for argv, _kwargs in runs
            if isinstance(argv, (list, tuple)) and "--yes" in argv
        ]
        assert terminal
        argv = list(terminal[0])
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


async def test_ready_escape_dismisses_with_added_key(
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
        await pilot.press("escape")
        await pilot.pause()

        assert dismissed
        result = dismissed[-1]
        assert isinstance(result, NewProjectSelection)
        assert result.outcome == "added"
        assert result.project_key == "gh_sase-org__new"


async def test_ready_plus_dismisses_wizard_before_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.new_project_modal import NewProjectModal

    from sase.ace.tui.modals import new_project_apply

    monkeypatch.setattr(new_project_apply, "ensure_project_tag_catalog", lambda: None)
    app = _WizardApp()
    modal = NewProjectModal(provider_metadata=())
    events: list[str] = []

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        modal._ready_key = "gh_sase-org__new"
        modal._ready_name = "new"
        modal.dismiss = lambda _result=None: events.append("wizard")  # type: ignore[method-assign]
        modal._dismiss_center_underneath = lambda: events.append("admin-center")  # type: ignore[method-assign]
        app._start_custom_agent_from_selection = lambda _selection: events.append(
            "launch"
        )  # type: ignore[attr-defined]

        await modal._ensure_catalog_and_launch()

    assert events == ["wizard", "admin-center", "launch"]


async def test_ready_current_invalidates_project_launch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.new_project_modal import NewProjectModal
    from sase.current_project import SetCurrentProjectOutcome

    invalidations: list[bool] = []
    reloads: list[bool] = []
    pane = SimpleNamespace(
        _invalidate_current_project_indicator=lambda: invalidations.append(True)
    )
    outcome = SetCurrentProjectOutcome(
        status="set", project=None, message="Set current project"
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply.set_current_project",
        lambda _key: outcome,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._find_projects_pane",
        lambda _app: pane,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._reload_projects_if_mounted",
        lambda _app: reloads.append(True),
    )
    app = _WizardApp()
    modal = NewProjectModal(provider_metadata=())

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await modal._set_current_key("gh_sase-org__new")

    assert invalidations == [True]
    assert reloads == [True]


def test_reload_projects_if_mounted_calls_pane_action() -> None:
    pane = MagicMock()
    pane.is_mounted = True
    screen = SimpleNamespace(query=lambda *_args, **_kwargs: [pane])
    app = SimpleNamespace(screen_stack=[screen])
    _reload_projects_if_mounted(app)
    pane.action_reload_projects.assert_called_once()


def test_find_projects_pane_walks_screen_stack_not_app_query() -> None:
    pane = MagicMock()
    pane.is_mounted = True
    queried = MagicMock()
    queried.is_mounted = True
    app = MagicMock()
    app.query.return_value = [queried]
    app.screen_stack = []
    assert _find_projects_pane(app) is None

    screen = SimpleNamespace(query=lambda *_args, **_kwargs: [pane])
    app.screen_stack = [object(), screen]
    assert _find_projects_pane(app) is pane


def test_find_projects_pane_skips_non_sequence_stack() -> None:
    pane = MagicMock()
    pane.is_mounted = True
    app = MagicMock()
    app.screen_stack = MagicMock()
    app.query.return_value = [pane]
    assert _find_projects_pane(app) is None


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
        {},
        TrackedProcCompletion(
            proc_info=_proc(), success=False, message="failed", output=""
        ),
    )
    assert called == [app]


def test_durable_add_completion_keeps_request_preferences_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferences: list[object] = []
    integrations: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._persist_add_preferences_async",
        lambda intent: preferences.append(dict(intent)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_apply._integrate_added_project_if_mounted",
        lambda app, key: integrations.append((app, key)),
    )

    class _Gone:
        is_mounted = False

    app = object()
    intent = {
        "mode": "add",
        "workflow_type": "gh",
        "owner": "sase-org",
        "project_key": "gh_sase-org__new",
    }
    _on_project_add_complete(
        app,
        weakref.ref(_Gone()),
        intent,
        TrackedProcCompletion(proc_info=_proc(), success=True, message="ok", output=""),
    )

    assert preferences == [intent]
    assert integrations == [(app, "gh_sase-org__new")]


def test_intent_uses_owner_and_project_key_from_apply_submission() -> None:
    submission = apply_submission(_document("new"))

    intent = _intent_from_submission(submission)

    assert intent["workflow_type"] == "gh"
    assert intent["owner"] == "sase-org"
    assert intent["project_key"] == "gh_sase-org__new"


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


def _failed_create_view() -> ProgressView:
    view = ProgressView()
    view.feed_event(
        {
            "event": "plan",
            "plan": {
                "steps": [
                    {"id": "create_remote", "label": "Create sase-org/forge"},
                    {"id": "checkout", "label": "Clone and register"},
                ]
            },
        }
    )
    view.feed_event({"event": "step", "id": "create_remote", "status": "done"})
    view.feed_event(
        {
            "event": "step",
            "id": "checkout",
            "status": "failed",
            "message": "clone failed",
            "hint": "retry the same plan",
        }
    )
    return view


def test_create_setup_incomplete_detects_created_remote() -> None:
    assert create_setup_incomplete(_failed_create_view()) is True


def test_create_setup_incomplete_ignores_clean_or_add_runs() -> None:
    add_view = ProgressView()
    add_view.feed_event(
        {
            "event": "plan",
            "plan": {"steps": [{"id": "checkout", "label": "Clone and register"}]},
        }
    )
    add_view.feed_event(
        {"event": "step", "id": "checkout", "status": "failed", "message": "nope"}
    )
    assert create_setup_incomplete(add_view) is False

    pending_view = ProgressView()
    pending_view.feed_event(
        {
            "event": "plan",
            "plan": {"steps": [{"id": "create_remote", "label": "Create x"}]},
        }
    )
    assert create_setup_incomplete(pending_view) is False


def test_format_elapsed_and_raw_log_disclosure() -> None:
    assert format_elapsed(3) == "3s"
    assert format_elapsed(75) == "1m 15s"
    collapsed = _render_raw_log(["one", "two"], expanded=False)
    assert "▸ raw log (2 lines)" in collapsed.plain
    assert "one" not in collapsed.plain
    expanded = _render_raw_log(["one", "two"], expanded=True)
    assert "▾ raw log (2 lines)" in expanded.plain
    assert "two" in expanded.plain
