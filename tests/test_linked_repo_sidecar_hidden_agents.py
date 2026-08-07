"""Tests for the hidden ``agents`` sidecar role."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    DEFAULT_AGENTS_DESCRIPTION,
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
    assert HIDDEN_SIDECAR_ROLES == frozenset({"agents"})
    assert agents["name"] == "widget--agents"
    assert agents["description"] == DEFAULT_AGENTS_DESCRIPTION
    assert agents["auto_clone"] is False
    assert agents["visibility"] == "public"
    assert agents["_sase_sidecar_slug"] == "widget--agents"
    assert agents["_sase_sidecar_repo_ref"] == "acme/widget--agents"
    assert agents["_sase_sidecar_remote_url"] == (
        "git@github.com:acme/widget--agents.git"
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
