"""Create identity and default-selection tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import new_project_create as create
from sase.workspace_provider._hookspec import (
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)
from ._new_project_create_helpers import fake_provider_fixture, probe


def test_owner_defaults_prefer_last_used_then_project_then_account() -> None:
    owners = ["sase-org", "bbugyi200", "sase-org"]
    assert (
        create._default_create_owner(
            owners,
            account="bbugyi200",
            last_owner="sase-org",
            current_project_owner="bbugyi200",
            workflow_type="gh",
        )
        == "sase-org"
    )
    assert (
        create._default_create_owner(
            owners,
            account="bbugyi200",
            last_owner="gone",
            current_project_owner="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )
    assert (
        create._default_create_owner(
            ["sase-org"],
            account="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )
    assert (
        create._default_create_owner(
            ["sase-org"],
            account="bbugyi200",
            workflow_type="gh",
            unavailable={"bbugyi200"},
        )
        == "sase-org"
    )
    assert (
        create._default_create_owner(
            [],
            account="bbugyi200",
            workflow_type="gh",
        )
        == "bbugyi200"
    )


def test_owner_defaults_skip_unavailable_and_support_bare_git() -> None:
    assert (
        create._default_create_owner(
            ["sase-org", "bbugyi200"],
            account="bbugyi200",
            last_owner="sase-org",
            workflow_type="gh",
            unavailable={"sase-org", "bbugyi200"},
        )
        == ""
    )
    assert (
        create._default_create_owner(
            [],
            account="bbugyi200",
            workflow_type="git",
        )
        == ""
    )
    assert (
        create._default_create_owner(
            ["docs"],
            account="bbugyi200",
            last_owner="bbugyi200",
            workflow_type="git",
        )
        == "docs"
    )


def test_visibility_defaults_to_private_then_last_supported_choice() -> None:
    supported = ("private", "public")
    assert (
        create._default_create_visibility(
            owner="sase-org", supported=supported, last_visibility={}
        )
        == "private"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=supported,
            last_visibility={"sase-org": "public"},
        )
        == "public"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=("private",),
            last_visibility={"sase-org": "public"},
        )
        == "private"
    )
    assert (
        create._default_create_visibility(
            owner="sase-org",
            supported=supported,
            last_visibility={"sase-org": "public"},
            unavailable={"public"},
        )
        == "private"
    )


def test_supported_visibilities_follow_provider_choice_field() -> None:
    form = RepoCreationForm(
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
                    RepoCreationChoice(value="internal", label="Internal"),
                ),
            ),
        ),
        can_create=True,
    )
    assert create._supported_create_visibilities(form) == ("private", "internal")
    assert create._supported_create_visibilities(None) == ("private", "public")


def test_normalize_create_name_preserves_provider_identity(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("gh", "sase-org", "  new  ")
    assert identity.valid
    assert identity.canonical_ref == "sase-org/new"
    assert identity.identity_key == "github.com/sase-org/new"
    assert identity.checkout_dir == "/home/user/projects/github/sase-org/new/"
    assert identity.project_key_base == "gh_sase-org__new"
    assert identity.project_name_base == "new"
    assert identity.web_url == "https://github.com/sase-org/new"
    assert identity.normalized_label == ""


def test_normalize_create_name_rejects_blank_and_unknown(
    fake_provider: None,
) -> None:
    blank = create.normalize_create_name("gh", "sase-org", "   ")
    assert not blank.valid
    assert blank.error
    empty_name = create.normalize_create_name("gh", "sase-org", "sase-org/")
    assert not empty_name.valid
    assert empty_name.error


def test_normalized_label_shows_only_genuine_changes() -> None:
    assert (
        create.CreateIdentity(
            valid=True, canonical_ref="a/b", normalized_from="a/B"
        ).normalized_label
        == "a/B → a/b"
    )
    assert create.CreateIdentity(valid=True, canonical_ref="a/b").normalized_label == ""
    assert create.CreateIdentity(valid=False, error="blank").normalized_label == ""


def test_normalize_bare_git_supports_empty_namespace(
    fake_provider: None,
) -> None:
    identity = create.normalize_create_name("git", "", "notes")
    assert identity.valid
    assert identity.identity_key == "git:/repos/notes.git"
    assert identity.checkout_dir == "/home/user/projects/git/notes/"


def test_classify_probe_maps_all_states() -> None:
    assert create.classify_create_probe(probe("not_found")).status == "available"
    assert create.classify_create_probe(probe("found")).status == "taken"
    assert create.classify_create_probe(None).status == "unavailable"
    assert (
        create.classify_create_probe(probe("unavailable", error_kind="auth")).status
        == "unavailable"
    )
    denied = create.classify_create_probe(
        probe("unavailable", error_kind="auth", message="permission denied")
    )
    assert denied.status == "unavailable"
    assert "permission denied" in denied.reason
    assert create.classify_create_probe(probe("bogus")).status == "unavailable"


def test_probe_result_current_rejects_every_stale_dimension() -> None:
    current = {
        "generation": 3,
        "expected_generation": 3,
        "mode": "create",
        "expected_mode": "create",
        "owner": "sase-org",
        "expected_owner": "sase-org",
        "identity_key": "github.com/sase-org/new",
        "expected_identity_key": "github.com/sase-org/new",
    }
    assert create._probe_result_current(**current)
    assert not create._probe_result_current(
        **{**current, "generation": 2},
    )
    assert not create._probe_result_current(**{**current, "mode": "add"})
    assert not create._probe_result_current(
        **{**current, "expected_owner": "other"},
    )
    assert not create._probe_result_current(
        **{**current, "identity_key": "github.com/sase-org/old"},
    )
