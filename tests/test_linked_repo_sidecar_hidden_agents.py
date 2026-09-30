"""Tests for the hidden ``agents`` and ``attachments`` sidecar roles."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
    ATTACHMENTS_SIDECAR_ROLE,
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION,
    HIDDEN_SIDECAR_ROLES,
    inject_default_linked_repos,
    merged_sidecar_entries_from_config,
)
from sase.linked_repos import (
    hidden_sidecar_clone_dir,
    resolve_linked_repos_for_project,
    sdd_sidecar_clone_dirname,
)
from tests._linked_repo_resolution_helpers import _project_file, _set_github_origin


def test_managed_project_injects_hidden_agents_sidecar_config(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/acme/widget.git")

    entries = inject_default_linked_repos(
        [],
        primary_workspace_dir=str(primary),
        local_config={"is_sase_managed": True},
    )

    agents = next(
        entry
        for entry in entries
        if entry.get("_sase_sidecar_role") == AGENTS_SIDECAR_ROLE
    )
    assert HIDDEN_SIDECAR_ROLES == frozenset(
        {"agents", "attachments", "attachments-private"}
    )
    assert agents["name"] == "widget--agents"
    assert agents["description"] == DEFAULT_AGENTS_DESCRIPTION
    assert agents["auto_clone"] is False
    assert agents["visibility"] == "public"
    assert agents["_sase_sidecar_slug"] == "widget--agents"
    assert agents["_sase_sidecar_repo_ref"] == "acme/widget--agents"
    assert agents["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--agents.git"
    )

    attachments = next(
        entry
        for entry in entries
        if entry.get("_sase_sidecar_role") == ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    )
    assert attachments["name"] == "widget--attachments-private"
    assert attachments["description"] == DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION
    assert attachments["auto_clone"] is False
    assert attachments["auto_sync"] is False
    assert attachments["visibility"] == "private"
    assert attachments["_sase_sidecar_slug"] == "widget--attachments-private"
    assert attachments["_sase_sidecar_repo_ref"] == "acme/widget--attachments-private"
    assert attachments["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--attachments-private.git"
    )

    public = next(
        entry
        for entry in entries
        if entry.get("_sase_sidecar_role") == ATTACHMENTS_SIDECAR_ROLE
    )
    assert public["name"] == "widget--attachments"
    assert public["description"] == DEFAULT_ATTACHMENTS_DESCRIPTION
    assert public["auto_clone"] is False
    assert public["auto_sync"] is False
    assert public["visibility"] == "public"
    assert public["_sase_sidecar_slug"] == "widget--attachments"
    assert public["_sase_sidecar_repo_ref"] == "acme/widget--attachments"
    assert public["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--attachments.git"
    )

    assert (
        inject_default_linked_repos(
            [],
            primary_workspace_dir=str(primary),
            local_config={},
        )
        == []
    )


@pytest.mark.parametrize(
    ("override", "expected_disabled", "expected_visibility"),
    [
        ({"disabled": True}, True, "public"),
        ({"visibility": "private"}, False, "private"),
    ],
)
def test_explicit_agents_override_suppresses_implicit_default(
    tmp_path: Path,
    override: dict[str, object],
    expected_disabled: bool,
    expected_visibility: str,
) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "is_sase_managed": True,
        "repos": {"sidecar": {"builtin": {"agents": {**override}}}},
    }
    configured = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )

    entries = inject_default_linked_repos(
        configured,
        primary_workspace_dir=str(primary),
        local_config=config,
    )

    agents_entries = [
        entry for entry in entries if entry.get("_sase_sidecar_role") == "agents"
    ]
    assert len(agents_entries) == 1
    agents = agents_entries[0]
    assert agents["name"] == "agents"
    assert agents["disabled"] is expected_disabled
    assert agents["visibility"] == expected_visibility
    assert agents["_sase_sidecar_slug"] == "widget--agents"
    assert agents["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--agents.git"
    )


def test_attachments_private_visibility_is_forced_private(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                "builtin": {
                    "attachments-private": {"visibility": "public"},
                    "agents": {"visibility": "private"},
                }
            }
        },
    }

    entries = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )
    by_role = {
        entry.get("_sase_sidecar_role"): entry
        for entry in entries
        if entry.get("_sase_sidecar_role")
    }

    # The private attachment store is private-only: an explicit public
    # visibility never survives merging (preflight fails it closed).
    assert by_role["attachments-private"]["visibility"] == "private"
    # No other role's default changes.
    assert by_role["agents"]["visibility"] == "private"


def test_hidden_agents_sidecar_never_resolves_for_launch(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "repos": {
                "sidecar": {
                    "builtin": {
                        "agents": {
                            "repo": "acme/shared-agents",
                            "auto_clone": True,
                        }
                    }
                }
            },
        },
        materialize=False,
    )

    assert resolution.repos == ()
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "agents",
            config={"repos": {"sidecar": {"builtin": {"agents": {}}}}},
        )
        is None
    )
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "widget--plans",
            config={
                "repos": {
                    "sidecar": {"builtin": {"agents": {"repo": "acme/widget--plans"}}}
                }
            },
        )
        is None
    )
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "shared-agents",
            config={
                "repos": {
                    "sidecar": {"builtin": {"agents": {"repo": "acme/shared-agents"}}}
                }
            },
        )
        is None
    )


def test_hidden_sidecar_clone_dir_is_machine_and_project_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))

    assert hidden_sidecar_clone_dir("gh_acme__widget", "agents") == str(
        (
            tmp_path / "state" / "projects" / "gh_acme__widget" / "repos" / "agents"
        ).resolve()
    )

    for project_key, role in [
        ("../widget", "agents"),
        ("widget", "../agents"),
        (".widget", "agents"),
        ("widget", "agents/other"),
        ("widget ", "agents"),
    ]:
        with pytest.raises(ValueError, match="safe path component"):
            hidden_sidecar_clone_dir(project_key, role)


def test_public_attachments_injected_only_for_public_beads(tmp_path: Path) -> None:
    from sase._linked_repo_config import inject_default_linked_repos

    primary = tmp_path / "widget"
    primary.mkdir()
    from tests._linked_repo_resolution_helpers import _set_github_origin

    _set_github_origin(primary, "https://github.com/acme/widget.git")
    # Private beads suppress the public attachments role.
    config = {
        "is_sase_managed": True,
        "repos": {"sidecar": {"builtin": {"beads": {"visibility": "private"}}}},
    }
    from sase._linked_repo_config import merged_sidecar_entries_from_config

    configured = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )
    entries = inject_default_linked_repos(
        configured,
        primary_workspace_dir=str(primary),
        local_config=config,
        config=config,
    )
    roles = {e.get("_sase_sidecar_role") for e in entries}
    assert "attachments" not in roles

    # Explicit disabled suppresses the injection the same way other hiddens work.
    config_disabled = {
        "is_sase_managed": True,
        "repos": {"sidecar": {"builtin": {"attachments": {"disabled": True}}}},
    }
    configured_disabled = merged_sidecar_entries_from_config(
        config_disabled, primary_workspace_dir=str(primary)
    )
    entries_disabled = inject_default_linked_repos(
        configured_disabled,
        primary_workspace_dir=str(primary),
        local_config=config_disabled,
        config=config_disabled,
    )
    roles_disabled = [
        e for e in entries_disabled if e.get("_sase_sidecar_role") == "attachments"
    ]
    assert len(roles_disabled) == 1
    assert roles_disabled[0].get("disabled") is True


def test_attachments_visibility_is_forced_public(tmp_path: Path) -> None:
    from sase._linked_repo_config import merged_sidecar_entries_from_config

    primary = tmp_path / "widget"
    primary.mkdir()
    from tests._linked_repo_resolution_helpers import _set_github_origin

    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {"builtin": {"attachments": {"visibility": "private"}}},
        },
    }
    entries = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )
    by_role = {
        entry.get("_sase_sidecar_role"): entry
        for entry in entries
        if entry.get("_sase_sidecar_role")
    }
    assert by_role["attachments"]["visibility"] == "public"
