"""Generic SDD sidecar-role coverage."""

from pathlib import Path

import pytest

from sase.sdd.store import (
    SddMaterializationError,
    document_sidecar_roles,
    read_sdd_store_record,
    resolve_sdd_store,
    write_sdd_store_record,
)


def test_custom_sidecar_record_without_research_routes_generic_role(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch("bare_git")

    written = write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "git@github.com:owner/repo--plans.git",
                },
                "designs": {
                    "repo": "owner/repo--designs",
                    "remote_url": "git@github.com:owner/repo--designs.git",
                },
            },
        },
    )

    designs = written.sidecar_for_kind("designs")
    assert designs is not None
    assert written.sidecar_for_kind("research") is None
    assert read_sdd_store_record(primary) == written
    store = resolve_sdd_store(workspace, 2)
    designs_root = workspace / "sase" / "repos" / "designs"
    assert store.kind_root("designs") == designs_root
    assert store.repo_root_for_kind("designs") == designs_root
    assert store.remote_url_for_kind("designs") == designs.remote_url
    with pytest.raises(ValueError, match="no research root"):
        store.kind_root("research")


def test_document_sidecar_roles_exclude_non_document_reserved_roles() -> None:
    roles = ("plans", "beads", "research", "agents", "designs", "research")

    assert document_sidecar_roles(roles) == ("research", "designs")
    assert document_sidecar_roles(roles, include_plans=True) == (
        "plans",
        "research",
        "designs",
    )


def _write_agents_sidecar_record(primary: Path) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "git@github.com:owner/repo--plans.git",
                },
                "agents": {
                    "repo": "owner/repo--agents",
                    "remote_url": "git@github.com:owner/repo--agents.git",
                },
            },
        },
    )


def test_agents_sidecar_degrades_when_project_key_unresolvable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch("bare_git")
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda *_args, **_kwargs: None,
    )
    _write_agents_sidecar_record(primary)

    store = resolve_sdd_store(workspace, 2)

    assert "agents" not in store.sidecar_dirs
    assert "agents" not in store.split_sidecar_roles()
    assert (
        "could not resolve the owning SASE project key for the agents sidecar"
        in store.unresolved_sidecars["agents"]
    )
    with pytest.raises(
        SddMaterializationError,
        match="could not resolve the owning SASE project key",
    ):
        store.kind_root("agents")
    assert store.kind_root("plans") == workspace / "sase" / "repos" / "plans"


def test_agents_sidecar_resolves_with_known_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    from sase.core.paths import sase_projects_dir

    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch("bare_git")
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda *_args, **_kwargs: "acme-widget",
    )
    _write_agents_sidecar_record(primary)

    store = resolve_sdd_store(workspace, 2)

    expected = sase_projects_dir() / "acme-widget" / "repos" / "agents"
    assert store.kind_root("agents") == expected
    assert "agents" in store.split_sidecar_roles()
    assert not store.unresolved_sidecars
