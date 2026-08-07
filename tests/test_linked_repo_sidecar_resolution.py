"""Tests for linked repository sidecar resolution and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    DEFAULT_AGENTS_DESCRIPTION,
    HIDDEN_SIDECAR_ROLES,
    _merge_resolution_config,
    inject_default_linked_repos,
    configured_sidecar_roles,
    merged_sidecar_entries_from_config,
)
from sase.linked_repos import (
    hidden_sidecar_clone_dir,
    resolve_linked_repos_for_project,
    sdd_sidecar_clone_dirname,
)
from sase.sdd.store import write_sdd_store_record
from tests._linked_repo_resolution_helpers import _project_file, _set_github_origin


def test_configured_sidecar_resolves_role_slug_and_remote(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/sase-org/sase.git")
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "repo": "sase-org/shared-research",
                        "visibility": "private",
                    }
                ]
            },
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.name == "research"
    assert repo.kind == "sidecar"
    assert repo.slug == "shared-research"
    assert repo.remote_url == "git@github.com:sase-org/shared-research.git"
    assert repo.primary_dir == str((primary / "sase" / "repos" / "research").resolve())
    assert repo.workspace_dir == str(
        (tmp_path / "sase_4" / "sase" / "repos" / "research").resolve()
    )


def test_configured_sidecar_ignores_poisoned_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:acme/widget--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={
            "repos": {
                "sidecar": [{"name": "research", "repo": "sase-org/sase--research"}]
            }
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    assert resolution.repos[0].remote_url == (
        "git@github.com:sase-org/sase--research.git"
    )


def test_configured_sidecar_preserves_consistent_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "https://github.com/sase-org/sase--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={
            "repos": {
                "sidecar": [{"name": "research", "repo": "sase-org/sase--research"}]
            }
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert resolution.repos[0].remote_url == (
        "git@github.com:sase-org/sase--research.git"
    )


def test_unpinned_configured_sidecar_ignores_stale_store_repo(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:sase-org/sase--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={"repos": {"sidecar": [{"name": "research"}]}},
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.name == "research"
    assert repo.slug == "widget--research"
    assert repo.remote_url == "git@github.com:acme/widget--research.git"


def test_disabled_sidecar_suppresses_matching_implicit_default(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    plans = tmp_path / "sase--plans"
    research = tmp_path / "sase--research"
    for path in (primary, plans, research):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "workspace": {"root": "adjacent"},
            "repos": {"sidecar": [{"name": "research", "disabled": True}]},
        },
        materialize=False,
    )

    assert [repo.name for repo in resolution.repos] == ["sase--plans"]


def test_project_sidecar_entry_overrides_global_entry_by_role(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    merged = _merge_resolution_config(
        {
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "repo": "sase-org/shared-research",
                        "visibility": "public",
                    }
                ]
            }
        },
        {
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "visibility": "private",
                        "disabled": True,
                    }
                ]
            }
        },
    )

    entries = merged_sidecar_entries_from_config(
        merged,
        primary_workspace_dir=str(primary),
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "sase-org/shared-research"
    assert entries[0]["visibility"] == "private"
    assert entries[0]["disabled"] is True


def test_managed_project_injects_default_plans_and_beads_sidecars(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    plans = tmp_path / "sase--plans"
    beads = tmp_path / "sase--beads"
    for path in (primary, plans, beads):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "workspace": {"root": "adjacent"},
            "linked_repos": [],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert [(repo.name, repo.auto_clone) for repo in resolution.repos] == [
        ("sase--plans", True),
        ("sase--beads", True),
    ]
    assert [Path(repo.workspace_dir) for repo in resolution.repos] == [
        tmp_path / "sase_4" / "sase" / "repos" / "plans",
        tmp_path / "sase_4" / "sase" / "repos" / "beads",
    ]


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
        "repos": {"sidecar": [{"name": "agents", **override}]},
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
                "sidecar": [
                    {
                        "name": "agents",
                        "repo": "acme/shared-agents",
                        "auto_clone": True,
                    }
                ]
            },
        },
        materialize=False,
    )

    assert resolution.repos == ()
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "agents",
            config={"repos": {"sidecar": [{"name": "agents"}]}},
        )
        is None
    )
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "widget--plans",
            config={
                "repos": {"sidecar": [{"name": "agents", "repo": "acme/widget--plans"}]}
            },
        )
        is None
    )
    assert (
        sdd_sidecar_clone_dirname(
            primary,
            "shared-agents",
            config={
                "repos": {"sidecar": [{"name": "agents", "repo": "acme/shared-agents"}]}
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


def test_default_sidecars_honor_override_and_opt_out(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    override = tmp_path / "custom-research"
    for path in (primary, override):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    overridden = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "linked_repos": [
                {
                    "name": "sase--research",
                    "path": "../custom-research",
                    "auto_clone": True,
                }
            ],
        },
        materialize=False,
    )
    assert [repo.name for repo in overridden.repos] == ["sase--research"]
    assert overridden.repos[0].primary_dir == str(override.resolve())
    assert overridden.repos[0].auto_clone is True

    opted_out = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "default_linked_repos": False,
            "linked_repos": [],
        },
        materialize=False,
    )
    assert opted_out.repos == ()
    assert opted_out.warnings == ()


def test_missing_default_sidecars_are_skipped_quietly(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={"is_sase_managed": True, "linked_repos": []},
        materialize=False,
    )

    assert resolution.repos == ()
    assert resolution.warnings == ()


def test_sidecar_dirname_uses_defaults_and_store_record(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    primary.mkdir()

    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) == "plans"
    assert sdd_sidecar_clone_dirname(primary, "main--research", config={}) is None
    assert sdd_sidecar_clone_dirname(primary, "main--beads", config={}) == "beads"
    assert sdd_sidecar_clone_dirname(primary, "core", config={}) is None

    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "owner/custom-plans",
                    "remote_url": "git@example.com:owner/custom-plans.git",
                },
                "research": {
                    "repo": "custom-research",
                    "remote_url": "git@example.com:owner/custom-research.git",
                },
                "designs": {
                    "repo": "owner/custom-designs",
                    "remote_url": "git@example.com:owner/custom-designs.git",
                },
            },
        },
    )

    assert sdd_sidecar_clone_dirname(primary, "custom-plans", config={}) == "plans"
    assert (
        sdd_sidecar_clone_dirname(primary, "custom-research", config={}) == "research"
    )
    assert sdd_sidecar_clone_dirname(primary, "custom-designs", config={}) == "designs"
    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) is None

    pinned_config = {
        "repos": {"sidecar": [{"name": "research", "repo": "owner/shared-research"}]}
    }
    assert (
        sdd_sidecar_clone_dirname(primary, "research", config=pinned_config)
        == "research"
    )
    assert (
        sdd_sidecar_clone_dirname(primary, "shared-research", config=pinned_config)
        == "research"
    )
    assert (
        sdd_sidecar_clone_dirname(primary, "custom-research", config=pinned_config)
        is None
    )


def _sidecar_role_view(entry: object) -> dict[str, object]:
    """Project one normalized entry down to its shape-independent fields."""

    assert isinstance(entry, dict)
    return {
        key: value
        for key, value in entry.items()
        if key
        in {
            "name",
            "repo",
            "description",
            "auto_clone",
            "disabled",
            "visibility",
            "_sase_sidecar_role",
            "_sase_sidecar_slug",
        }
    }


def test_bucketed_and_legacy_sidecar_shapes_normalize_identically(
    tmp_path: Path,
) -> None:
    """Both ``repos.sidecar`` shapes produce the same normalized entries."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    legacy = {
        "repos": {
            "sidecar": [
                {"name": "plans", "auto_clone": True},
                {"name": "beads", "auto_clone": True},
                {"name": "agents", "visibility": "private"},
                {"name": "research", "description": "Durable research."},
            ]
        }
    }
    bucketed = {
        "repos": {
            "sidecar": {
                "builtin": {
                    "plans": {"auto_clone": True},
                    "beads": {"auto_clone": True},
                    "agents": {"visibility": "private"},
                },
                "custom": {"research": {"description": "Durable research."}},
            }
        }
    }

    legacy_entries = merged_sidecar_entries_from_config(
        legacy, primary_workspace_dir=str(primary)
    )
    bucketed_entries = merged_sidecar_entries_from_config(
        bucketed, primary_workspace_dir=str(primary)
    )

    assert [_sidecar_role_view(entry) for entry in bucketed_entries] == [
        _sidecar_role_view(entry) for entry in legacy_entries
    ]


def test_bucketed_sidecar_roles_emit_builtin_order_then_configured_custom_order(
    tmp_path: Path,
) -> None:
    """Builtin roles emit in canonical order; custom roles keep config order."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                # Deliberately authored out of canonical order.
                "builtin": {
                    "agents": {},
                    "beads": {"auto_clone": True},
                    "plans": {"auto_clone": True},
                },
                "custom": {"designs": {}, "research": {}},
            }
        }
    }

    assert configured_sidecar_roles(
        config, primary_workspace_dir=str(primary), include_hidden=True
    ) == ("plans", "beads", "agents", "designs", "research")


def test_bucketed_sidecar_layers_merge_per_role_key(tmp_path: Path) -> None:
    """A later layer's ``disabled`` merges into the inherited custom entry."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    merged = _merge_resolution_config(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "repo": "sase-org/shared-research",
                            "visibility": "public",
                        }
                    }
                }
            }
        },
        {"repos": {"sidecar": {"custom": {"research": {"disabled": True}}}}},
    )

    entries = merged_sidecar_entries_from_config(
        merged, primary_workspace_dir=str(primary)
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "sase-org/shared-research"
    assert entries[0]["visibility"] == "public"
    assert entries[0]["disabled"] is True


def test_bucketed_sidecar_role_in_both_buckets_resolves_to_custom(
    tmp_path: Path,
) -> None:
    """``custom`` wins for a role mis-declared in both buckets."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                "builtin": {"plans": {"repo": "acme/builtin-plans"}},
                "custom": {"plans": {"repo": "acme/custom-plans"}},
            }
        }
    }

    entries = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "acme/custom-plans"


def test_bucketed_sidecar_skips_non_mapping_values(tmp_path: Path) -> None:
    """Runtime parsing stays forgiving; doctor is what reports bad shapes."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                "builtin": "nope",
                "custom": {"research": {}, "designs": "nope"},
            }
        }
    }

    entries = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )

    assert [entry["name"] for entry in entries] == ["research"]
