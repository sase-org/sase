"""Create Review, durable apply, and CLI-equality coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import weakref

import pytest
from textual.widgets import Button, Input, Static

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals._new_project_apply_flow import (
    _intent_from_submission,
    _terminal_apply_argv,
)
from sase.ace.tui.modals._new_project_apply_shared import (
    on_project_apply_complete,
    record_successful_create_preferences,
)
from sase.ace.tui.modals.new_project_create import NewProjectCreateConfigure
from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from sase.ace.tui.modals.new_project_create_model import (
    create_review_request,
    lenient_effective_options,
    normalize_create_name,
)
from sase.ace.tui.modals.new_project_review import (
    NewProjectReview,
    _check_argv,
)
from sase.ace.tui.modals.new_project_review_model import (
    apply_submission,
    build_review,
    options_from_argv,
    strip_transport_flags,
)
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now
from sase import workspace_provider
from sase.main.parser import create_parser
from sase.main import project_handler_add as add_cli
from sase.ops.io import write_operation_request
from sase.ops.models import REQUEST_ENV, DurableOperationRequest
from sase.project_onboarding.preferences import load_preferences
from sase.project_onboarding.planning import build_plan_document
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
    WorkflowMetadata,
)
from tests.ace.tui.modals.test_new_project_configure_review import _WizardApp
from tests.ace.tui.modals._new_project_create_helpers import (
    enter_create_stage,
    make_modal,
)
from tests.ace.tui.modals.test_new_project_review_checks import _ReviewApp
from tests.project_onboarding.test_cli import _create_args


def _create_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "kind": "project_onboarding_plan",
        "mode": "create",
        "status": "ready",
        "intent_fingerprint": "c" * 64,
        "provider": {"workflow_type": "gh", "display": "GitHub"},
        "target": {
            "ref": "sase-org/new",
            "display": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "host": "github.com",
            "owner": "sase-org",
            "web_url": "https://github.com/sase-org/new",
            "visibility": "private",
            "checkout_dir": "/tmp/new",
        },
        "project": {
            "key": "gh_sase-org__new",
            "name": "new",
            "accent": "#B9589C",
        },
        "creation": {
            "visibility": "private",
            "summary": ["GitHub repository"],
        },
        "steps": [
            {
                "id": "checkout",
                "operation": "create",
                "label": "Clone and register",
                "detail": "/tmp/new",
                "state": "pending",
            }
        ],
        "warnings": [],
        "blockers": [],
        "apply_argv": [
            "sase",
            "project",
            "create",
            "sase-org/new",
            "--description",
            "--yes",
            "--visibility",
            "private",
            "--option",
            "readme=--json",
            "--yes",
            "--json",
        ],
    }
    document.update(overrides)
    return document


def _create_proc() -> ObservedProc:
    return ObservedProc(
        proc_id="create-1",
        proc_type="project.create",
        cl_name="",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
    )


def _sync_persist(intent: Any) -> None:
    record_successful_create_preferences(
        str(intent.get("workflow_type") or ""),
        str(intent.get("owner") or ""),
        str(intent.get("visibility") or ""),
    )


def test_options_from_argv_keeps_transport_spellings_as_data() -> None:
    argv = [
        "sase",
        "project",
        "create",
        "sase-org/new",
        "--description",
        "--yes",
        "--visibility",
        "private",
        "--option",
        "readme=--json",
        "-O",
        "template=--check",
        "--yes",
        "--json",
        "--check",
    ]
    assert options_from_argv(argv) == {
        "description": "--yes",
        "visibility": "private",
        "readme": "--json",
        "template": "--check",
    }
    stripped = strip_transport_flags(argv)
    assert stripped == [
        "sase",
        "project",
        "create",
        "sase-org/new",
        "--description",
        "--yes",
        "--visibility",
        "private",
        "--option",
        "readme=--json",
        "-O",
        "template=--check",
    ]
    assert _terminal_apply_argv(argv) == [*stripped, "--yes"]


def test_create_check_argv_preserves_option_values() -> None:
    argv = _check_argv(_create_document())
    assert argv == [
        "sase",
        "project",
        "create",
        "sase-org/new",
        "--description",
        "--yes",
        "--visibility",
        "private",
        "--option",
        "readme=--json",
        "--check",
        "--json",
    ]


def test_create_apply_submission_matches_cli_request_from_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _create_document(
        apply_argv=[
            "sase",
            "project",
            "create",
            "sase-org/new",
            "--option",
            "description=--yes",
            "--visibility",
            "private",
            "--option",
            "readme=--json",
            "--yes",
            "--json",
        ]
    )
    submission = apply_submission(document)
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")
    monkeypatch.setattr(
        add_cli,
        "_target_for_ref",
        lambda _ref, **_kwargs: {
            "ref": "sase-org/new",
            "identity_key": "github.com/sase-org/new",
            "workflow_type": "gh",
            "owner": "sase-org",
        },
    )
    monkeypatch.setattr(
        add_cli,
        "parse_create_ref",
        lambda text: ParsedRepoRef(
            workflow_type="gh",
            ref=text,
            identity_key="github.com/sase-org/new",
            display=text,
        ),
    )
    monkeypatch.setattr(add_cli, "resolve_request_path", lambda _args: Path("/request"))
    monkeypatch.setattr(
        add_cli,
        "load_request",
        lambda *_a, **_k: DurableOperationRequest(
            operation="project.create",
            payload={"request": submission.request},
        ),
    )
    args = _create_args(
        [
            "gh:sase-org/new",
            "--option",
            "description=--yes",
            "--visibility",
            "private",
            "--option",
            "readme=--json",
            "--yes",
            "--json",
        ]
    )
    request = add_cli._request_from_args(
        args, mode="create", operation="project.create"
    )
    assert request["options"] == submission.request["options"]
    assert request["options"]["description"] == "--yes"
    assert request["options"]["readme"] == "--json"


@pytest.mark.parametrize("workflow_type", ["git", "gh"])
def test_create_submission_round_trips_through_request_sidecar(
    workflow_type: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wizard's durable intent and emitted CLI argv share one target."""
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    owner = "sase-org" if workflow_type == "gh" else ""
    name = "new" if workflow_type == "gh" else "tools"
    canonical_ref = f"{owner}/{name}" if owner else name
    git_identity = f"git:{sase_home / 'repos' / f'{name}.git'}"
    gh_identity = f"github.com/{canonical_ref}"

    def parse(workflow: str, raw: str) -> ParsedRepoRef | None:
        if workflow != workflow_type:
            return None
        value = raw.strip()
        if workflow == "git":
            bare_name = value.removeprefix("git:")
            if not bare_name or "/" in bare_name:
                return None
            return ParsedRepoRef(
                workflow_type="git",
                ref=bare_name,
                identity_key=git_identity,
                display=bare_name,
                name=bare_name,
                owner="",
                project_key_base=bare_name,
                project_name_base=bare_name,
                checkout_dir=str(sase_home / "projects" / "git" / bare_name) + "/",
            )
        ref = value.removeprefix("gh:")
        if "/" not in ref:
            return None
        namespace, repo = ref.split("/", 1)
        return ParsedRepoRef(
            workflow_type="gh",
            ref=ref,
            identity_key=gh_identity,
            display=ref,
            owner=namespace,
            name=repo,
            host="github.com",
            web_url=f"https://github.com/{ref}",
            project_key_base=f"gh_{namespace}__{repo}",
            project_name_base=repo,
            checkout_dir=str(sase_home / "projects" / "github" / namespace / repo)
            + "/",
        )

    metadata = tuple(
        WorkflowMetadata(
            workflow_type=workflow,
            ref_pattern="",
            display_name="Bare git" if workflow == "git" else "GitHub",
            pre_allocated_env_prefix="",
        )
        for workflow in ("git", "gh")
    )
    if workflow_type == "git":
        form = RepoCreationForm(
            workflow_type="git",
            namespace="",
            fields=(
                RepoCreationField(name="bare_dir", label="Bare path", kind="line"),
            ),
            can_create=True,
        )
        visibility = ""
    else:
        form = RepoCreationForm(
            workflow_type="gh",
            namespace=owner,
            fields=(
                RepoCreationField(
                    name="visibility",
                    label="Visibility",
                    kind="choice",
                    default="private",
                    choices=(
                        RepoCreationChoice(value="private", label="Private"),
                        RepoCreationChoice(value="public", label="Public"),
                    ),
                ),
            ),
            can_create=True,
        )
        visibility = "private"
    monkeypatch.setattr(
        workspace_provider, "get_all_workflow_metadata", lambda: metadata
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parse)
    monkeypatch.setattr(
        workspace_provider,
        "get_display_name",
        lambda workflow: "Bare git" if workflow == "git" else "GitHub",
    )
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", lambda *_a: form)
    monkeypatch.setattr(add_cli, "detect_actor", lambda **_kwargs: "human")

    identity = normalize_create_name(workflow_type, owner, name)
    options = lenient_effective_options(
        form, {"visibility": visibility} if visibility else {}
    )
    request = create_review_request(
        identity=identity,
        workflow_type=workflow_type,
        provider_display="Bare git" if workflow_type == "git" else "GitHub",
        project=ConfigureDraft(name=name, setup_override="off"),
        visibility=visibility,
        effective_options=options,
    )
    fields = [
        {
            "name": field.name,
            "label": field.label,
            "kind": field.kind,
            "default": field.default,
            "choices": [
                {"value": choice.value, "label": choice.label}
                for choice in field.choices
            ],
        }
        for field in form.fields
    ]
    document = build_plan_document(
        request,
        facts={
            "remote": {
                "status": "not_found",
                "visibility": "",
                "is_empty": None,
                "is_archived": None,
                "can_push": None,
                "sase_managed": False,
                "repo_id": "",
                "default_branch": "",
                "message": "",
                "web_url": "",
            },
            "checkout": {"state": "absent"},
            "projects": [],
            "can_create": True,
            "creation_fields": fields,
            "creation_effective": options,
        },
    )
    submission = apply_submission(document)
    if workflow_type == "git":
        assert "--visibility" not in submission.argv
        assert "visibility" not in submission.request["creation"]
        assert "visibility" not in submission.request["options"]

    request_path = tmp_path / f"{workflow_type}-request.json"
    write_operation_request(
        request_path,
        DurableOperationRequest(
            operation="project.create",
            payload={"request": submission.request},
        ),
    )
    monkeypatch.setenv(REQUEST_ENV, str(request_path))
    args = create_parser(only="project").parse_args(list(submission.argv[1:]))
    parsed_request = add_cli._request_from_args(
        args, mode="create", operation="project.create"
    )
    assert parsed_request["target"]["identity_key"] == identity.identity_key
    assert parsed_request["target"]["ref"] == identity.canonical_ref


async def test_create_review_renders_danger_heading_and_keep_notice() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.show_document(_create_document())
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
    document = _create_document(
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
        public = _create_document()
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
        await pilot.pause(0.6)
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


def test_dismissed_create_success_records_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    reloads: list[object] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared.reload_projects_if_mounted",
        lambda app: reloads.append(app),
    )

    class _Gone:
        is_mounted = False

    app = object()
    document = _create_document()
    intent = _intent_from_submission(apply_submission(document))
    on_project_apply_complete(
        app,
        weakref.ref(_Gone()),
        intent,
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=True,
            message="created",
            output="",
        ),
    )
    assert reloads == [app]
    prefs = load_preferences()
    assert prefs.last_visibility == {"sase-org": intent["visibility"]}
    assert prefs.last_owner == {"gh": "sase-org"}
    assert prefs.last_provider == "gh"


def test_failed_create_does_not_overwrite_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    from sase.project_onboarding.preferences import record_visibility_selection

    record_visibility_selection("sase-org", "private")

    class _Gone:
        is_mounted = False

    intent = {
        "mode": "create",
        "workflow_type": "gh",
        "owner": "sase-org",
        "visibility": "public",
    }
    on_project_apply_complete(
        object(),
        weakref.ref(_Gone()),
        intent,
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=False,
            message="failed",
            output="",
        ),
    )
    assert load_preferences().last_visibility == {"sase-org": "private"}


def test_add_complete_does_not_record_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_create_preferences_async",
        _sync_persist,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_add_preferences_async",
        lambda _intent: None,
    )
    from sase.ace.tui.modals._new_project_apply_shared import on_project_add_complete

    class _Gone:
        is_mounted = False

    on_project_add_complete(
        object(),
        weakref.ref(_Gone()),
        {"mode": "add", "workflow_type": "gh", "owner": "sase-org"},
        TrackedProcCompletion(
            proc_info=_create_proc(),
            success=True,
            message="added",
            output="",
        ),
    )
    assert load_preferences().last_visibility == {}
