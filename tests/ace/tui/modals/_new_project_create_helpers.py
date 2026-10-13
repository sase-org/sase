"""Shared setup for new-project create tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase import workspace_provider
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)


def parsed(workflow_type: str, text: str) -> ParsedRepoRef | None:
    if workflow_type == "git":
        name = text.removeprefix("git:")
        if not name or "/" in name:
            return None
        return ParsedRepoRef(
            workflow_type="git",
            ref=name,
            identity_key=f"git:/repos/{name}.git",
            display=name,
            owner="",
            name=name,
            project_key_base=name,
            project_name_base=name,
            checkout_dir=f"/home/user/projects/git/{name}/",
        )
    ref = text
    if "://" in ref:
        ref = ref.split("://", 1)[1]
        if "/" in ref:
            ref = ref.split("/", 1)[1]
    ref = ref.removesuffix(".git")
    if "/" not in ref:
        return None
    owner, name = ref.split("/", 1)
    if not owner or not name:
        return None
    text = f"{owner}/{name}"
    return ParsedRepoRef(
        workflow_type=workflow_type,
        ref=text,
        identity_key=f"github.com/{text}".casefold(),
        display=text,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"/home/user/projects/github/{owner}/{name}/",
        web_url=f"https://github.com/{text}",
    )


def repo_form() -> RepoCreationForm:
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
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
            RepoCreationField(
                name="description", label="Description", kind="line", default=""
            ),
            RepoCreationField(
                name="readme", label="README", kind="bool", default="true"
            ),
            RepoCreationField(
                name="template",
                label="Template",
                kind="line",
                group="advanced",
                excludes=("readme",),
            ),
        ),
        can_create=True,
    )


@pytest.fixture(name="fake_provider")
def fake_provider_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parsed)


def probe(status: str, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "status": status,
        "visibility": "",
        "is_empty": None,
        "is_archived": None,
        "can_push": None,
        "sase_managed": None,
        "repo_id": "",
        "default_branch": "",
        "message": "",
        "web_url": "",
        "error_kind": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _CreateApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("host")


def make_modal(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> tuple[_CreateApp, Any, list[str], list[str]]:
    from sase.ace.tui.modals.new_project_modal import NewProjectModal
    from sase.project_onboarding import Preferences
    from sase.workspace_provider import WorkflowMetadata
    from tests.ace.tui.modals._new_project_source_helpers import inputs

    probe_calls: list[str] = []
    describe_calls: list[str] = []
    probe_status = overrides.get("probe_status", "not_found")
    form: RepoCreationForm | None = overrides.get("form", repo_form())

    def _probe_repo(workflow_type: str, ref: str) -> SimpleNamespace:
        probe_calls.append(ref)
        if isinstance(probe_status, Exception):
            raise probe_status
        return probe(probe_status)

    def _describe(workflow_type: str, namespace: str) -> RepoCreationForm | None:
        describe_calls.append(namespace)
        return form

    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parsed)
    monkeypatch.setattr(workspace_provider, "probe_repo", _probe_repo)
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", _describe)
    modal = NewProjectModal(
        current_workflow_type=overrides.get("current_workflow_type"),
        current_project_owner=str(overrides.get("current_project_owner") or ""),
        provider_metadata=(
            WorkflowMetadata(
                workflow_type="gh",
                ref_pattern=r"^$",
                display_name="GitHub",
                pre_allocated_env_prefix="",
            ),
        ),
        candidate_inputs=overrides.get("candidate_inputs", {"gh": inputs()}),
        preferences=overrides.get(
            "preferences",
            Preferences(
                last_owner={"gh": "sase-org"},
                last_visibility={"sase-org": "public"},
            ),
        ),
    )
    app = _CreateApp()
    return app, modal, probe_calls, describe_calls


async def enter_create_stage(pilot: Any, modal: Any, **kwargs: Any) -> None:
    modal.enter_create_configure(
        workflow_type="gh",
        owners=["sase-org", "bbugyi200"],
        account="bbugyi200",
        **kwargs,
    )
    await pilot.pause(0.6)
