"""Basic repo-inventory collection tests.

Split from ``tests.test_repo_inventory``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_inventory import RepoRecord, collect_repo_inventory, repo_display_name
from sase.sdd.store import write_sdd_store_record
from tests._repo_inventory_helpers import project_record, set_github_origin

__all__ = [
    "test_explicit_disabled_project_is_included",
    "test_inventory_collects_all_repo_kinds_and_sidecar_wins_overlap",
    "test_inventory_surfaces_configured_sidecar_role_and_slug",
    "test_repo_display_name_prefers_slug_then_name",
]


def test_repo_display_name_prefers_slug_then_name() -> None:
    record = RepoRecord(
        name="inventory-name",
        kind="primary",
        project="widget",
        project_key="widget",
        path="/repos/widget",
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
    )

    assert repo_display_name(record) == "inventory-name"
    assert repo_display_name(replace(record, slug="hosted-slug")) == "hosted-slug"


def test_inventory_collects_all_repo_kinds_and_sidecar_wins_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    linked = tmp_path / "widget-core"
    linked.mkdir()
    plans_clone = primary / "sase" / "repos" / "plans"
    plans_clone.mkdir(parents=True)
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
    config = {
        "linked_repos": [
            {
                "name": "widget--plans",
                "path": "../legacy-plans",
                "description": "Plans from config",
                "auto_clone": True,
            },
            {
                "name": "widget-core",
                "path": str(linked),
                "description": "Shared core",
                "auto_clone": True,
            },
            {"name": "missing-docs", "path": "../missing-docs"},
        ]
    }
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    assert [record.kind for record in inventory.records] == [
        "primary",
        "sidecar",
        "sidecar",
        "linked",
        "linked",
    ]
    by_name = {record.name: record for record in inventory.records}
    assert by_name["widget"].exists is True
    assert by_name["widget--plans"].path == str(plans_clone)
    assert by_name["widget--plans"].source == "SDD store record"
    assert by_name["widget--research"].exists is False
    assert by_name["widget-core"].env_name == "WIDGET_CORE"
    assert by_name["missing-docs"].exists is False
    assert sum(record.name == "widget--plans" for record in inventory.records) == 1


def test_inventory_surfaces_configured_sidecar_role_and_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    set_github_origin(Path(project.workspace_dir or ""))
    config = {
        "repos": {
            "sidecar": {
                "custom": {
                    "designs": {
                        "repo": "acme/shared-designs",
                        "description": "Shared design documents",
                        "visibility": "private",
                    }
                }
            }
        }
    }
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    sidecar = next(record for record in inventory.records if record.kind == "sidecar")
    assert sidecar.name == "designs"
    assert sidecar.slug == "shared-designs"
    assert sidecar.path == str(
        (Path(project.workspace_dir or "") / "sase" / "repos" / "designs").resolve()
    )
    assert sidecar.exists is False
    assert sidecar.source == "repos.sidecar config"
    assert sidecar.remote_url == "git@github.com:acme/shared-designs.git"


def test_explicit_disabled_project_is_included(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(
        tmp_path,
        key="old_widget",
        display_name="old-widget",
        state="disabled",
    )
    calls: list[object] = []

    def list_records(*args: object, **kwargs: object) -> list[ProjectRecordWire]:
        calls.append((args, kwargs))
        return [project]

    monkeypatch.setattr("sase.repo_inventory.list_project_records", list_records)
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: {},
    )

    inventory = collect_repo_inventory(project="old-widget")

    assert [record.name for record in inventory.records] == ["old-widget"]
    assert calls
    assert calls[0][0][1] == "all"
