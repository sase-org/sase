"""Workspace-clone and external-repo tests for the repo inventory.

Split from ``tests.test_repo_inventory``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.linked_repos import external_repo_clone_dir
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.store import write_sdd_store_record
from sase.workspace_provider.registry import load_registry, save_registry
from sase.workspace_provider.store import WorkspaceStore
from tests._repo_inventory_helpers import project_record, workspace_entry

__all__ = [
    "test_inventory_joins_registered_workspace_clone_matrix",
    "test_inventory_scans_external_repos_across_registered_workspaces",
]


def test_inventory_joins_registered_workspace_clone_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    linked = tmp_path / "widget-core"
    linked.mkdir()
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@example.test:acme/widget--plans.git",
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": "git@example.test:acme/widget--research.git",
                },
            },
        },
    )
    workspace_root = tmp_path / "managed"
    config = {
        "workspace": {"root": str(workspace_root)},
        "linked_repos": [
            {
                "name": "widget-core",
                "path": str(linked),
            }
        ],
    }
    store = WorkspaceStore(str(primary), config=config)
    registry = load_registry(store)
    workspace_10 = tmp_path / "widget_10"
    workspace_10.mkdir()
    workspace_12 = tmp_path / "widget_12"
    registry.workspaces["10"] = workspace_entry(workspace_10)
    registry.workspaces["12"] = workspace_entry(workspace_12)
    save_registry(store, registry)

    plans_10 = workspace_10 / "sase" / "repos" / "plans"
    plans_10.mkdir(parents=True)
    linked_10 = workspace_10 / "sase" / "repos" / "linked" / "widget-core"
    linked_10.mkdir(parents=True)

    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")
    by_name = {record.name: record for record in inventory.records}

    primary_clones = by_name["widget"].clones
    assert [clone.workspace_num for clone in primary_clones] == [0, 10, 12]
    assert [clone.exists for clone in primary_clones] == [True, True, False]

    plans_clones = by_name["widget--plans"].clones
    assert plans_clones[1].path == str(plans_10)
    assert plans_clones[1].exists is True
    assert plans_clones[2].exists is False

    linked_clones = by_name["widget-core"].clones
    assert linked_clones[0].path == str(linked)
    assert linked_clones[1].path == str(linked_10)
    assert linked_clones[1].exists is True
    assert linked_clones[2].exists is False


def test_inventory_scans_external_repos_across_registered_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    workspace_root = tmp_path / "managed"
    config = {"workspace": {"root": str(workspace_root)}}
    store = WorkspaceStore(str(primary), config=config)
    registry = load_registry(store)
    workspace_10 = tmp_path / "widget_10"
    workspace_10.mkdir()
    workspace_12 = tmp_path / "widget_12"
    workspace_12.mkdir()
    registry.workspaces["10"] = workspace_entry(workspace_10)
    registry.workspaces["12"] = workspace_entry(workspace_12)
    save_registry(store, registry)

    gh_clone = Path(external_repo_clone_dir(workspace_10, "gh", "acme", "tool"))
    gh_clone.mkdir(parents=True)
    project_clone = Path(external_repo_clone_dir(workspace_12, "projects", "dotdrop"))
    project_clone.mkdir(parents=True)

    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")
    externals = [record for record in inventory.records if record.kind == "external"]

    assert [record.name for record in externals] == ["dotdrop", "gh:acme/tool"]
    assert all(record.source == "opened external" for record in externals)
    assert all(record.auto_clone is False for record in externals)
    by_name = {record.name: record for record in externals}
    assert by_name["dotdrop"].path == str(project_clone)
    assert [clone.workspace_num for clone in by_name["gh:acme/tool"].clones] == [
        0,
        10,
        12,
    ]
    assert [clone.exists for clone in by_name["gh:acme/tool"].clones] == [
        False,
        True,
        False,
    ]
