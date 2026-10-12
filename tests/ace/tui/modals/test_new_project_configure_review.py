"""Configure and Review interaction coverage for the New Project wizard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Button, Input, OptionList

from sase import workspace_provider
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now
from sase.ace.tui.modals.new_project_configure import NewProjectConfigure
from sase.ace.tui.modals.new_project_configure_model import (
    ConfigureDraft,
    IdentityCheck,
)
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.new_project_review import (
    NewProjectReview,
    _check_argv,
    _run_check,
)
from sase.ace.tui.modals.new_project_review_model import apply_submission
from sase.ace.tui.modals.new_project_source import NewProjectSource
from tests.ace.tui.modals.test_new_project_source import (
    _ModalApp,
    _inputs,
    _parsed,
    _provider,
)


class _WizardApp(_ModalApp):
    CSS_PATH = Path(__file__).parents[4] / "src/sase/ace/tui/styles.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.submit_calls: list[tuple[Any, dict[str, Any]]] = []
        self.submit_result: ObservedProc | None = ObservedProc(
            proc_id="add-1",
            proc_type="project.add",
            cl_name="",
            project_file="",
            status="running",
            message="running",
            started_at=local_now(),
        )

    def _submit_durable_proc(self, argv: Any, **kwargs: Any) -> ObservedProc | None:
        self.submit_calls.append((argv, kwargs))
        return self.submit_result


def _document(name: str = "new", *, blocked: bool = False) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "add",
        "status": "ready",
        "intent_fingerprint": "a" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "checkout_dir": "/tmp/new",
            "visibility": "private",
        },
        "project": {"key": "gh_sase-org__new", "accent": "#B9589C"},
        "setup": {
            "enabled": True,
            "code": "unmanaged_can_push",
            "reason": "Recommended",
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "state": "pending",
                "label": "Clone and register",
                "detail": "/tmp/new",
            }
        ],
        "warnings": [],
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "add",
            "sase-org/new",
            "--name",
            name,
            "--yes",
            "--json",
        ],
    }
    if blocked:
        document["status"] = "blocked"
        document["blockers"] = [
            {"message": "Checkout is occupied", "hint": "Choose another path."}
        ]
    return document


def _select_suggested(modal: NewProjectModal) -> None:
    source = modal.query_one(NewProjectSource)
    row = next(row for row in source._rows.values() if row.group == "suggested")
    options = source.query_one(OptionList)
    index = next(
        index
        for index in range(options.option_count)
        if options.get_option_at_index(index).id == row.row_id
    )
    options.highlighted = index
    source.choose_highlighted()


async def _tab_to_review(pilot: Any, modal: NewProjectModal) -> None:
    button = modal.query_one("#new-project-configure-review", Button)
    for _ in range(12):
        if modal.screen.focused is button:
            break
        await pilot.press("tab")
    assert modal.screen.focused is button


def _patch_fast_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    def preview(self: NewProjectModal) -> None:
        self._preview_generation += 1
        draft = self._state.draft
        assert draft is not None
        self._local_plan = _document(draft.name)
        self._local_plan_draft = draft
        self.query_one(NewProjectConfigure).apply_preview(
            self._local_plan, IdentityCheck("unique", "")
        )

    monkeypatch.setattr(NewProjectModal, "_schedule_local_preview", preview)


def _make_add_flow(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, NewProjectModal]:
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, ref: (
            _parsed(workflow_type, ref) if ref == "sase-org/new" else None
        ),
    )
    _patch_fast_preview(monkeypatch)
    modal = NewProjectModal(
        provider_metadata=(_provider("gh", "GitHub"),),
        candidate_inputs={"gh": _inputs()},
    )
    app = _WizardApp()
    return app, modal


async def test_configure_keeps_draft_when_going_back_and_ignores_printable_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        assert modal._state.stage == "configure"
        name = modal.query_one("#new-project-configure-name", Input)
        name.value = "renamed"
        await pilot.pause(0.4)
        assert modal._state.draft is not None
        assert modal._state.draft.name == "renamed"

        await pilot.press("b")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert name.value != "renamed"

        name.value = "renamed"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal.screen.focused is not name
        await pilot.press("escape")
        await pilot.pause()
        assert modal._state.stage == "source"

        _select_suggested(modal)
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal._state.draft is not None
        assert modal._state.draft.name == "renamed"


async def test_review_back_restores_draft_and_y_stores_model_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, _document: self.show_document(_document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        configure = modal.query_one(NewProjectConfigure)
        name = configure.query_one("#new-project-configure-name", Input)
        name.value = "renamed"
        await pilot.pause(0.4)
        review_button = configure.query_one("#new-project-configure-review", Button)
        assert not review_button.disabled
        await _tab_to_review(pilot, modal)
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "review"

        await pilot.press("b")
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal._state.draft is not None
        assert modal._state.draft.name == "renamed"
        assert modal._local_plan
        assert modal._state.draft == modal._local_plan_draft
        assert not configure.query_one("#new-project-configure-review", Button).disabled

        await _tab_to_review(pilot, modal)
        await pilot.press("enter")
        await pilot.pause()
        assert modal._state.stage == "review"
        await pilot.press("y")
        await pilot.pause()
        assert modal._state.stage == "progress"
        assert modal._apply_submission == apply_submission(_document("renamed"))


async def test_blocked_review_cannot_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, _plan: self.show_document(_document("new", blocked=True)),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        await _tab_to_review(pilot, modal)
        await pilot.press("enter")
        await pilot.pause()
        review = modal.query_one(NewProjectReview)
        assert review.query_one("#new-project-review-confirm", Button).disabled
        assert (
            modal.query_one("#new-project-stages").current == "new-project-review-stage"
        )
        assert modal.screen.focused.id == "new-project-review-back"
        await pilot.press("y")
        await pilot.pause()
        assert modal._state.stage == "review"
        assert modal._apply_submission is None


async def test_local_preview_ignores_stale_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_modal.validate_draft",
        lambda _target, draft, _records: _document(draft.name),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        row = modal._state.selected
        assert row is not None
        modal._preview_generation += 1
        newest_generation = modal._preview_generation
        newest = ConfigureDraft(name="latest")
        modal._state.set_draft(newest)
        configure = modal.query_one(NewProjectConfigure)
        configure.set_source(row, newest)

        await modal._build_local_preview(
            newest_generation - 1,
            row.row_id,
            dict(modal._active_target),
            list(modal._active_records),
            ConfigureDraft(name="stale"),
        )
        assert modal._local_plan.get("apply_argv") == _document("new")["apply_argv"]

        await modal._build_local_preview(
            newest_generation,
            row.row_id,
            dict(modal._active_target),
            list(modal._active_records),
            newest,
        )
        assert modal._local_plan.get("apply_argv") == _document("latest")["apply_argv"]


def test_review_check_argv_and_return_code_one_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _document()
    argv = _check_argv(document)
    assert argv == [
        "sase",
        "project",
        "add",
        "sase-org/new",
        "--name",
        "new",
        "--check",
        "--json",
    ]

    class Reporter:
        def log(self, _message: str) -> None:
            pass

    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_review.subprocess.run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"returncode": 1, "stdout": '{"status":"blocked"}', "stderr": ""},
        )(),
    )
    result = _run_check(argv, "/tmp", 10, Reporter())  # type: ignore[arg-type]
    assert result.success
    assert result.payload == {"status": "blocked"}
