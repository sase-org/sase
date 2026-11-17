"""CLI-equality coverage for create review apply argv and durable requests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase import workspace_provider
from sase.ace.tui.modals._new_project_apply_flow import _terminal_apply_argv
from sase.ace.tui.modals.new_project_configure_model import ConfigureDraft
from sase.ace.tui.modals.new_project_create_model import (
    create_review_request,
    lenient_effective_options,
    normalize_create_name,
)
from sase.ace.tui.modals.new_project_review import _check_argv
from sase.ace.tui.modals.new_project_review_model import (
    apply_submission,
    options_from_argv,
    strip_transport_flags,
)
from sase.main import project_handler_add as add_cli
from sase.main.parser import create_parser
from sase.ops.io import write_operation_request
from sase.ops.models import REQUEST_ENV, DurableOperationRequest
from sase.project_onboarding.planning import build_plan_document
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
    WorkflowMetadata,
)
from tests.ace.tui.modals._new_project_create_execution_helpers import create_document
from tests.project_onboarding._cli_test_support import make_create_args


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
    argv = _check_argv(create_document())
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
    document = create_document(
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
    monkeypatch.setattr(
        add_cli, "resolve_request_path", lambda _args, **_kwargs: Path("/request")
    )
    monkeypatch.setattr(
        add_cli,
        "load_request",
        lambda *_a, **_k: DurableOperationRequest(
            operation="project.create",
            payload={"request": submission.request},
        ),
    )
    args = make_create_args(
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
