"""Failed-resume recovery for the New Project wizard."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from sase.ace.tui.modals.new_project_resume import (
    ResumeContext,
    recover_resume_intent,
)
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.modals.new_project_source_model import SourceRow
from tests.ace.tui.modals.test_new_project_configure_review import (
    _document,
    _make_add_flow,
    _select_suggested,
)


def _row(**overrides: Any) -> SourceRow:
    data = {
        "identity_key": "github.com/sase-org/forge",
        "ref": "sase-org/forge",
        "display": "sase-org/forge",
        "project_name_base": "forge",
        "status": "failed",
    }
    data.update(overrides)
    return SourceRow(
        row_id=f"resume:{data['identity_key']}",
        group="resume",
        display=str(data["display"]),
        ref=str(data["ref"]),
        data=data,
    )


def _seed() -> dict[str, Any]:
    return {
        "ref": "sase-org/forge",
        "identity_key": "github.com/sase-org/forge",
        "project_name_base": "forge",
        "workflow_type": "gh",
    }


def test_recovers_requested_intent_from_operation_request() -> None:
    context = ResumeContext(
        journal={
            "mode": "add",
            "identity_key": "github.com/sase-org/forge",
            "workflow_type": "gh",
            "ref": "sase-org/forge",
        },
        request={
            "requested": {
                "name": "forge-renamed",
                "aliases": ["fg"],
                "setup": "off",
                "make_current": True,
            }
        },
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.error == ""
    assert plan.notice == ""
    assert plan.draft == ConfigureDraft(
        name="forge-renamed",
        aliases=("fg",),
        setup_override="off",
        make_current=True,
    )


def test_legacy_journal_without_intent_gets_review_notice() -> None:
    context = ResumeContext(
        journal={
            "mode": "add",
            "identity_key": "github.com/sase-org/forge",
            "ref": "sase-org/forge",
        },
        request=None,
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.error == ""
    assert "not recovered" in plan.notice
    assert plan.draft.name == "forge"


def test_command_argv_recovers_when_request_is_missing() -> None:
    context = ResumeContext(
        journal={"mode": "add", "identity_key": "github.com/sase-org/forge"},
        request=None,
        command=(
            "sase",
            "project",
            "add",
            "sase-org/forge",
            "--name",
            "from-argv",
            "--alias",
            "fa",
            "--setup",
            "--make-current",
            "--yes",
        ),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.draft.name == "from-argv"
    assert plan.draft.aliases == ("fa",)
    assert plan.draft.setup_override == "on"
    assert plan.draft.make_current is True


def test_mismatched_provider_is_recoverable_error() -> None:
    context = ResumeContext(
        journal={
            "mode": "add",
            "identity_key": "github.com/sase-org/forge",
            "workflow_type": "git",
            "ref": "sase-org/forge",
        },
        request=None,
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert "different provider" in plan.error


def test_create_mode_journal_is_rejected() -> None:
    context = ResumeContext(
        journal={"mode": "create", "identity_key": "github.com/sase-org/forge"},
        request=None,
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert "not an add" in plan.error


async def test_failed_resume_hydrates_review_and_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    context = ResumeContext(
        journal={
            "mode": "add",
            "identity_key": "github.com/sase-org/new",
            "workflow_type": "gh",
            "ref": "sase-org/new",
        },
        request={"requested": {"name": "resumed", "aliases": [], "setup": "auto"}},
        command=(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.load_resume_context",
        lambda _key: context,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.plan_configure_display",
        lambda _target, draft, _facts: _document(draft.name),
    )
    monkeypatch.setattr(
        NewProjectReview,
        "start_check",
        lambda self, document, notice="": self.show_document(document, notice=notice),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        row = modal._state.selected
        assert row is not None
        resume_row = SourceRow(
            row_id=row.row_id,
            group="resume",
            display=row.display,
            ref=row.ref,
            data=dict(row.data),
        )
        modal._state.select_source(resume_row)
        await modal._hydrate_failed_resume(
            modal._resume_generation,
            resume_row.row_id,
            "github.com/sase-org/new",
            "gh",
            resume_row,
        )
        assert modal._state.draft is not None
        assert modal._state.draft.name == "resumed"
        review = modal.query_one(NewProjectReview)
        assert review._document.get("apply_argv") == _document("resumed")["apply_argv"]
        modal._review_back_requested(None)  # type: ignore[arg-type]
        await pilot.pause()
        assert modal._state.stage == "configure"
        assert modal._state.draft.name == "resumed"


async def test_stale_resume_does_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.load_resume_context",
        lambda _key: ResumeContext(journal=None, request=None, command=()),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(modal)
        await pilot.pause()
        _select_suggested(modal)
        await pilot.pause()
        row = modal._state.selected
        assert row is not None
        modal._resume_generation += 1
        await modal._hydrate_failed_resume(
            modal._resume_generation - 1,
            row.row_id,
            "github.com/sase-org/new",
            "gh",
            row,
        )
        assert modal.query_one(NewProjectReview)._document == {}
