"""Failed-resume recovery for the New Project wizard."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from sase.ace.tui.modals.new_project_resume import (
    ResumeContext,
    recover_resume_intent,
)
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.modals.new_project_source_model import SourceRow, create_source_row
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


def _create_journal(**overrides: Any) -> dict[str, Any]:
    journal: dict[str, Any] = {
        "mode": "create",
        "identity_key": "github.com/sase-org/forge",
        "workflow_type": "gh",
        "ref": "sase-org/forge",
    }
    journal.update(overrides)
    return journal


def _create_request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "mode": "create",
        "actor": "human",
        "target": {
            "ref": "sase-org/forge",
            "workflow_type": "gh",
            "identity_key": "github.com/sase-org/forge",
            "owner": "sase-org",
        },
        "requested": {
            "name": "forge",
            "aliases": ["fg"],
            "setup": "off",
            "make_current": True,
        },
        "options": {"visibility": "private", "description": "A forge"},
        "creation": {"visibility": "private", "summary": []},
    }
    request.update(overrides)
    return request


def test_create_mode_journal_recovers_typed_request() -> None:
    context = ResumeContext(
        journal=_create_journal(),
        request=_create_request(),
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.error == ""
    assert plan.mode == "create"
    assert plan.create is not None
    assert plan.create.owner == "sase-org"
    assert plan.create.ref == "sase-org/forge"
    assert plan.create.visibility == "private"
    assert plan.create.options["description"] == "A forge"
    assert plan.draft.name == "forge"
    assert plan.draft.aliases == ("fg",)
    assert plan.draft.setup_override == "off"
    assert plan.draft.make_current is True


def test_create_mode_journal_falls_back_to_recorded_argv() -> None:
    context = ResumeContext(
        journal=_create_journal(),
        request=None,
        command=(
            "sase",
            "project",
            "create",
            "sase-org/forge",
            "--name",
            "forge",
            "--visibility",
            "public",
            "--option",
            "readme=true",
            "--no-setup",
            "--yes",
            "--json",
        ),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.error == ""
    assert plan.mode == "create"
    assert plan.create is not None
    assert plan.create.owner == "sase-org"
    assert plan.create.visibility == "public"
    assert plan.create.options["readme"] == "true"
    assert plan.create.options["visibility"] == "public"
    assert plan.draft.setup_override == "off"


def test_create_mode_journal_without_evidence_is_explicit_blocker() -> None:
    context = ResumeContext(
        journal=_create_journal(),
        request=None,
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.mode == "create"
    assert plan.create is None
    assert "not being reused" in plan.error
    assert "add" in plan.error
    assert plan.add_alternative == "sase-org/forge"


def test_create_resume_rejects_mismatched_provider() -> None:
    context = ResumeContext(
        journal=_create_journal(workflow_type="git"),
        request=_create_request(),
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.mode == "create"
    assert "different provider" in plan.error
    assert plan.add_alternative == "sase-org/forge"


def test_create_resume_rejects_stale_identity() -> None:
    request = _create_request()
    target = dict(request["target"])
    target["identity_key"] = "github.com/sase-org/other"
    request["target"] = target
    context = ResumeContext(
        journal=_create_journal(),
        request=request,
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert "no longer matches" in plan.error


def test_add_request_is_ignored_for_create_journal() -> None:
    context = ResumeContext(
        journal=_create_journal(),
        request={"mode": "add", "requested": {"name": "forge"}},
        command=(),
    )
    plan = recover_resume_intent(
        row=_row(), workflow_type="gh", context=context, seed_target=_seed()
    )
    assert plan.mode == "create"
    assert plan.create is None
    assert "not being reused" in plan.error


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


def _forge_parsed(workflow_type: str, ref: str) -> SimpleNamespace:
    owner, _, name = ref.partition("/")
    return SimpleNamespace(
        workflow_type=workflow_type,
        ref=ref,
        identity_key=f"github.com/{ref}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        checkout_dir="",
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        web_url=f"https://github.com/{ref}",
        normalized_from="",
    )


def _create_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "create",
        "status": "ready",
        "intent_fingerprint": "b" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/forge",
            "display": "sase-org/forge",
            "identity_key": "github.com/sase-org/forge",
            "owner": "sase-org",
            "checkout_dir": "",
            "visibility": "private",
        },
        "project": {"key": "gh_sase-org__forge", "accent": "#B9589C"},
        "steps": [],
        "warnings": [],
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "create",
            "sase-org/forge",
            "--visibility",
            "private",
            "--yes",
            "--json",
        ],
    }


def _not_found_probe() -> SimpleNamespace:
    return SimpleNamespace(
        status="not_found",
        visibility="",
        is_empty=None,
        is_archived=None,
        can_push=None,
        sase_managed=None,
        repo_id="",
        default_branch="",
        message="",
        web_url="",
        error_kind=None,
    )


def test_source_dispatch_routes_resume_and_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, modal = _make_add_flow(monkeypatch)
    calls: list[str] = []
    modal._start_failed_resume = lambda row: calls.append(f"resume:{row.row_id}")  # type: ignore[method-assign]
    modal._enter_create_from_source = lambda row: calls.append(f"create:{row.row_id}")  # type: ignore[method-assign]
    resume_row = SourceRow(
        row_id="resume:github.com/sase-org/forge",
        group="resume",
        display="sase-org/forge",
        ref="sase-org/forge",
        data={"status": "failed"},
    )
    modal._source_chosen(SimpleNamespace(row=resume_row))  # type: ignore[arg-type]
    modal._source_chosen(SimpleNamespace(row=create_source_row("GitHub", "gh")))  # type: ignore[arg-type]
    assert calls == [
        "resume:resume:github.com/sase-org/forge",
        "create:create:gh",
    ]


async def test_create_resume_hydrates_review_and_restores_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, modal = _make_add_flow(monkeypatch)
    previous_parse = workspace_provider.parse_repo_ref
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, ref: (
            _forge_parsed(workflow_type, ref)
            if ref == "sase-org/forge"
            else previous_parse(workflow_type, ref)
        ),
    )
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda _wt, _ref: _not_found_probe()
    )
    context = ResumeContext(
        journal=_create_journal(),
        request=_create_request(),
        command=(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.load_resume_context",
        lambda _key: context,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.assemble_create_facts",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.new_project_configure_flow.plan_create_display",
        lambda **_kwargs: _create_document(),
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
            display="sase-org/forge",
            ref="sase-org/forge",
            data={**dict(row.data), "identity_key": "github.com/sase-org/forge"},
        )
        modal._state.select_source(resume_row)
        await modal._hydrate_failed_resume(
            modal._resume_generation,
            resume_row.row_id,
            "github.com/sase-org/forge",
            "gh",
            resume_row,
        )
        assert modal._state.wizard_mode == "create"
        draft = modal._state.create_draft
        assert draft is not None
        assert draft.owner == "sase-org"
        assert draft.visibility == "private"
        assert draft.project.name == "forge"
        assert modal._create_resume_pending_restore is True
        review = modal.query_one(NewProjectReview)
        assert review._document.get("mode") == "create"
        assert review._document.get("apply_argv") == _create_document()["apply_argv"]
        modal._review_back_requested(None)  # type: ignore[arg-type]
        await pilot.pause()
        assert modal._state.stage == "create-configure"
        assert modal._state.create_draft is not None
        assert modal._state.create_draft.owner == "sase-org"
        assert modal._create_resume_pending_restore is False
