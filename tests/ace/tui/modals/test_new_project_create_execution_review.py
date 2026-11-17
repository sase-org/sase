"""Create Review rendering and wizard navigation coverage."""

from __future__ import annotations

import pytest
from textual.widgets import Button, Input, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.modals.new_project_review_model import apply_submission, build_review
from tests.ace.tui.modals._new_project_create_execution_helpers import create_document
from tests.ace.tui.modals._new_project_create_helpers import (
    enter_create_stage,
    make_modal,
)
from tests.ace.tui.modals.test_new_project_configure_review import _WizardApp
from tests.ace.tui.modals.test_new_project_review_checks import _ReviewApp


async def test_create_review_renders_danger_heading_and_keep_notice() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.show_document(create_document())
        heading = review.query_one("#new-project-review-card-heading", Static)
        confirm = review.query_one("#new-project-review-confirm", Button)
        state = review.query_one("#new-project-review-state", Static).render().plain
        assert review.has_class("danger")
        assert "CREATE" in heading.render().plain
        assert "PRIVATE" in heading.render().plain
        assert "sase-org/new" in heading.render().plain
        assert confirm.variant == "error"
        assert "Create repository" in str(confirm.label)
        assert "keeps the created repository" in state


def test_bare_git_create_review_omits_visibility_copy() -> None:
    document = create_document(
        provider={"workflow_type": "git", "display": "Bare git"},
        target={
            "ref": "tools",
            "display": "tools",
            "identity_key": "git:/tmp/sase/repos/tools.git",
            "checkout_dir": "/tmp/tools",
            "visibility": "local",
        },
        creation={"visibility": "private", "summary": []},
        creation_fields=[{"name": "bare_dir", "kind": "line"}],
        apply_argv=["sase", "project", "create", "git:tools", "--yes", "--json"],
    )

    view = build_review(document)
    assert view.visibility == ""
    assert view.heading == "CREATE tools"
    assert "PRIVATE" not in view.confirm_label


async def test_create_review_compact_heading_stays_visible() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(80, 24)):
        review = app.query_one(NewProjectReview)
        public = create_document()
        public["target"] = {**public["target"], "visibility": "public"}
        public["creation"] = {**public["creation"], "visibility": "public"}
        review.show_document(public)
        heading = (
            review.query_one("#new-project-review-card-heading", Static).render().plain
        )
        assert review.has_class("compact")
        assert review.has_class("danger")
        assert "CREATE" in heading
        assert "PUBLIC" in heading


async def test_create_review_button_enters_review_and_back_restores_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, modal, _, _ = make_modal(monkeypatch)
    app = _WizardApp()
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await wait_for(
            pilot,
            lambda: (
                modal._create_identity.name == "new"
                and modal._create_availability.status == "available"
            ),
        )
        assert modal._create_availability.status == "available"
        review_button = modal.query_one("#new-project-create-review", Button)
        assert not review_button.disabled
        review_button.press()
        await pilot.pause()
        assert modal._state.stage == "review"
        assert modal._state.wizard_mode == "create"
        review = modal.query_one(NewProjectReview)
        assert review.has_class("danger")
        heading = (
            review.query_one("#new-project-review-card-heading", Static).render().plain
        )
        assert "CREATE" in heading
        await pilot.press("b")
        await pilot.pause()
        assert modal._state.stage == "create-configure"
        assert modal.query_one(NewProjectCreateConfigure).display
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.raw_name == "new"


async def test_create_y_submits_project_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, modal, _, _ = make_modal(monkeypatch)
    app = _WizardApp()
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        modal.query_one("#new-project-create-review", Button).press()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert modal._state.stage == "progress"
        assert app.submit_calls
        argv, kwargs = app.submit_calls[0]
        expected = apply_submission(modal._review_document or modal._local_plan)
        assert kwargs["operation"] == "project.create"
        assert kwargs["request"]["mode"] == "create"
        assert kwargs["request"]["options"] == expected.request["options"]
        assert argv == list(expected.argv)


async def test_duplicate_create_stays_on_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, modal, _, _ = make_modal(monkeypatch)
    app = _WizardApp()
    app.submit_result = None
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document: self.show_document(document),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        await enter_create_stage(pilot, modal)
        modal.query_one("#new-project-create-name", Input).value = "new"
        await pilot.pause(0.6)
        modal.query_one("#new-project-create-review", Button).press()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert modal._state.stage == "review"
        assert modal._apply_submission is not None
        assert modal._apply_submission.operation == "project.create"
