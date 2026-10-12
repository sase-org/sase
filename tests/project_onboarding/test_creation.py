"""Tests for create-mode refs and strict GitHub form validation."""

from __future__ import annotations

import pytest

from sase import workspace_provider
from sase.project_onboarding.creation import (
    create_apply_ref,
    creation_form_has_field,
    evaluate_creation_options,
    parse_create_ref,
    parse_option_item,
)
from sase.project_onboarding.refs import UserRefError
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
    WorkflowMetadata,
)


def _metadata() -> list[WorkflowMetadata]:
    return [
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern="",
            display_name="GitHub",
            pre_allocated_env_prefix="",
        ),
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern="",
            display_name="Git",
            pre_allocated_env_prefix="",
        ),
    ]


def _parsed(workflow_type: str, ref: str, **overrides: str) -> ParsedRepoRef:
    payload = {
        "workflow_type": workflow_type,
        "ref": ref,
        "identity_key": f"{workflow_type}:{ref}",
        "display": ref,
        "owner": "",
        "name": ref.rsplit("/", 1)[-1],
    }
    payload.update(overrides)
    return ParsedRepoRef(**payload)


def _gh_form(*, internal_disabled: str = "") -> RepoCreationForm:
    internal_reason = internal_disabled or ""
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
        fields=(
            RepoCreationField(name="description", label="Description", kind="line"),
            RepoCreationField(
                name="visibility",
                label="Visibility",
                kind="choice",
                default="private",
                choices=(
                    RepoCreationChoice(value="public", label="Public"),
                    RepoCreationChoice(value="private", label="Private"),
                    RepoCreationChoice(
                        value="internal",
                        label="Internal",
                        disabled_reason=internal_reason,
                    ),
                ),
            ),
            RepoCreationField(
                name="add_readme",
                label="README",
                kind="bool",
                default="true",
            ),
            RepoCreationField(name="gitignore", label="gitignore", kind="search"),
            RepoCreationField(name="license", label="License", kind="search"),
            RepoCreationField(
                name="template",
                label="Template",
                kind="line",
                group="advanced",
                excludes=("add_readme", "gitignore", "license", "team"),
            ),
            RepoCreationField(
                name="include_all_branches",
                label="Include all branches",
                kind="bool",
                group="advanced",
                requires=("template",),
            ),
            RepoCreationField(
                name="homepage",
                label="Homepage",
                kind="line",
                group="advanced",
            ),
            RepoCreationField(
                name="team",
                label="Team",
                kind="search",
                group="advanced",
            ),
            RepoCreationField(
                name="issues",
                label="Issues",
                kind="bool",
                default="true",
                group="advanced",
            ),
            RepoCreationField(
                name="wiki",
                label="Wiki",
                kind="bool",
                default="true",
                group="advanced",
            ),
        ),
        can_create=True,
    )


@pytest.fixture
def create_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[tuple[str, str], ParsedRepoRef]:
    forge = _parsed(
        "gh",
        "sase-org/forge",
        owner="sase-org",
        identity_key="github.com/sase-org/forge",
    )
    table: dict[tuple[str, str], ParsedRepoRef] = {
        ("gh", "gh:sase-org/forge"): forge,
        ("gh", "sase-org/forge"): forge,
        ("git", "git:tools"): _parsed(
            "git", "tools", identity_key="git:/tmp/tools.git"
        ),
    }
    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(
        workspace_provider,
        "parse_repo_ref",
        lambda workflow_type, text: table.get((workflow_type, text)),
    )
    return table


class TestParseCreateRef:
    def test_accepts_prefixed_and_shorthand_github(
        self, create_providers: dict[tuple[str, str], ParsedRepoRef]
    ) -> None:
        del create_providers
        prefixed = parse_create_ref("gh:sase-org/forge")
        shorthand = parse_create_ref("sase-org/forge")
        assert prefixed.workflow_type == "gh"
        assert shorthand.ref == "sase-org/forge"
        assert prefixed.identity_key == shorthand.identity_key

    def test_accepts_git_name(
        self, create_providers: dict[tuple[str, str], ParsedRepoRef]
    ) -> None:
        del create_providers
        parsed = parse_create_ref("git:tools")
        assert parsed.workflow_type == "git"
        assert parsed.ref == "tools"

    @pytest.mark.parametrize(
        "raw",
        [
            "/tmp/repo.git",
            "~/projects/git/tools",
            "https://github.com/sase-org/forge",
            "git@github.com:sase-org/forge.git",
            "git:/tmp/tools.git",
            "tools",
            "",
        ],
    )
    def test_rejects_paths_urls_and_bare_names(
        self,
        create_providers: dict[tuple[str, str], ParsedRepoRef],
        raw: str,
    ) -> None:
        del create_providers
        with pytest.raises(UserRefError, match="create"):
            parse_create_ref(raw)

    def test_create_apply_ref_prefixes_bare_git_name(
        self, create_providers: dict[tuple[str, str], ParsedRepoRef]
    ) -> None:
        del create_providers
        assert create_apply_ref("git", "tools") == "git:tools"
        assert create_apply_ref("gh", "sase-org/forge") == "sase-org/forge"
        assert create_apply_ref("gh", "gh:sase-org/forge") == "gh:sase-org/forge"


class TestParseOptionItem:
    def test_splits_key_value(self) -> None:
        assert parse_option_item("visibility=private") == ("visibility", "private")
        assert parse_option_item("description=a=b") == ("description", "a=b")

    def test_rejects_missing_key_or_separator(self) -> None:
        with pytest.raises(ValueError, match="KEY=VALUE"):
            parse_option_item("visibility")
        with pytest.raises(ValueError, match="missing a key"):
            parse_option_item("=private")


class TestEvaluateGithubConstraints:
    @pytest.fixture
    def gh_form(self, monkeypatch: pytest.MonkeyPatch) -> RepoCreationForm:
        form = _gh_form(internal_disabled="personal accounts cannot use internal")

        def describe(workflow_type: str, namespace: str) -> RepoCreationForm:
            del workflow_type, namespace
            return form

        monkeypatch.setattr(workspace_provider, "describe_repo_creation", describe)
        return form

    def test_template_conflicts_with_license_and_gitignore(
        self, gh_form: RepoCreationForm
    ) -> None:
        del gh_form
        result = evaluate_creation_options(
            "gh",
            "sase-org",
            {"template": "sase-org/template", "license": "MIT", "gitignore": "Python"},
        )
        assert result["valid"] is False
        codes = {(item["field"], item["code"]) for item in result["errors"]}
        assert ("license", "conflict") in codes
        assert ("gitignore", "conflict") in codes

    def test_include_all_branches_requires_template(
        self, gh_form: RepoCreationForm
    ) -> None:
        del gh_form
        result = evaluate_creation_options(
            "gh",
            "sase-org",
            {"include_all_branches": "true"},
        )
        assert result["valid"] is False
        assert any(
            item["field"] == "include_all_branches" and item["code"] == "requires"
            for item in result["errors"]
        )

    def test_unknown_option(self, gh_form: RepoCreationForm) -> None:
        del gh_form
        result = evaluate_creation_options("gh", "sase-org", {"clone": "true"})
        assert result["valid"] is False
        assert any(item["code"] == "unknown_option" for item in result["errors"])

    def test_invalid_visibility_choice(self, gh_form: RepoCreationForm) -> None:
        del gh_form
        result = evaluate_creation_options("gh", "sase-org", {"visibility": "secret"})
        assert result["valid"] is False
        assert any(
            item["field"] == "visibility" and item["code"] == "invalid_choice"
            for item in result["errors"]
        )

    def test_disabled_internal_visibility(self, gh_form: RepoCreationForm) -> None:
        del gh_form
        result = evaluate_creation_options("gh", "sase-org", {"visibility": "internal"})
        assert result["valid"] is False
        assert any(
            item["field"] == "visibility" and item["code"] == "disabled_choice"
            for item in result["errors"]
        )

    def test_defaults_include_private_visibility(
        self, gh_form: RepoCreationForm
    ) -> None:
        del gh_form
        result = evaluate_creation_options("gh", "sase-org", {})
        assert result["valid"] is True
        assert result["effective_options"]["visibility"] == "private"
        names = [field["name"] for field in result["fields"]]
        assert "visibility" in names
        assert "template" in names
        assert creation_form_has_field("gh", "sase-org", "visibility") is True
        assert creation_form_has_field("gh", "sase-org", "clone") is False

    def test_missing_form_is_unknown_option(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workspace_provider, "describe_repo_creation", lambda *_a, **_k: None
        )
        result = evaluate_creation_options("gh", "sase-org", {"visibility": "private"})
        assert result["valid"] is False
        assert any(item["code"] == "unknown_option" for item in result["errors"])
