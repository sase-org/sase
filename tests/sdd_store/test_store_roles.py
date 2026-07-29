"""Generic SDD sidecar-role coverage."""

from pathlib import Path

import pytest

from sase.sdd.store import (
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
