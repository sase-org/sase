"""Repository inventory domain coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.store import write_sdd_store_record


def _project_record(
    tmp_path: Path,
    *,
    key: str = "gh_acme__widget",
    display_name: str = "widget",
    state: str = "enabled",
) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / key
    project_dir.mkdir(parents=True)
    primary = tmp_path / display_name
    primary.mkdir()
    project_file = project_dir / f"{key}.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\n", encoding="utf-8")
    return ProjectRecordWire(
        schema_version=3,
        project_name=key,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(primary),
        state=state,
        state_explicit=state == "disabled",
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled",
        display_name=display_name,
        is_project=True,
        vcs_kind="gh",
    )


def test_inventory_collects_all_repo_kinds_and_sidecar_wins_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
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
                    "remote_url": "https://example.test/widget--plans.git",
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": "https://example.test/widget--research.git",
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


def test_explicit_disabled_project_is_included(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(
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
