"""Repository inventory domain coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase._linked_repo_config import (
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
)
from sase.linked_repos import external_repo_clone_dir, hidden_sidecar_clone_dir
from sase.repo_inventory import RepoRecord, collect_repo_inventory, repo_display_name
from sase.sdd.store import write_sdd_store_record
from sase.workspace_provider.registry import (
    WorkspaceEntry,
    load_registry,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore


def _set_github_origin(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widget.git",
        ],
        cwd=path,
        check=True,
    )


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
    project = _project_record(tmp_path)
    _set_github_origin(Path(project.workspace_dir or ""))
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


@pytest.mark.parametrize(
    ("split_beads", "expected_auto_clone"),
    [(False, False), (True, True)],
)
def test_inventory_gates_beads_auto_clone_on_store_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    split_beads: bool,
    expected_auto_clone: bool,
) -> None:
    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    _set_github_origin(primary)
    sidecars = {
        "plans": {
            "repo": "acme/widget--plans",
            "remote_url": "git@example.test:acme/widget--plans.git",
        },
        "research": {
            "repo": "acme/widget--research",
            "remote_url": "git@example.test:acme/widget--research.git",
        },
    }
    if split_beads:
        sidecars["beads"] = {
            "repo": "acme/widget--beads",
            "remote_url": "git@example.test:acme/widget--beads.git",
        }
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3 if split_beads else 2,
            "storage": "sidecar_repos",
            "sidecars": sidecars,
        },
    )
    config = {
        "repos": {
            "sidecar": {
                "builtin": {
                    "beads": {
                        "auto_clone": True,
                        "description": DEFAULT_BEADS_DESCRIPTION,
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

    beads = next(record for record in inventory.records if record.name == "beads")
    assert beads.kind == "sidecar"
    assert beads.auto_clone is expected_auto_clone
    assert beads.description == DEFAULT_BEADS_DESCRIPTION
    assert beads.source == "repos.sidecar config"


def test_disabled_configured_sidecar_suppresses_store_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
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
    config = {"repos": {"sidecar": {"custom": {"research": {"disabled": True}}}}}
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    sidecars = [record for record in inventory.records if record.kind == "sidecar"]
    assert [record.name for record in sidecars] == ["widget--plans"]


def test_pinned_sidecar_identity_overrides_stale_store_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    _set_github_origin(primary)
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
        "repos": {"sidecar": {"custom": {"research": {"repo": "acme/shared-research"}}}}
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

    research = next(record for record in inventory.records if record.name == "research")
    assert research.slug == "shared-research"
    assert research.remote_url == "git@github.com:acme/shared-research.git"
    assert research.source == "repos.sidecar config"


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


def test_inventory_joins_registered_workspace_clone_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
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
    registry.workspaces["10"] = _workspace_entry(workspace_10)
    registry.workspaces["12"] = _workspace_entry(workspace_12)
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


def test_inventory_exposes_hidden_agents_at_one_machine_level_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    _set_github_origin(primary)
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    config = {"workspace": {"root": str(tmp_path / "managed")}}
    store = WorkspaceStore(str(primary), config=config)
    registry = load_registry(store)
    workspace_10 = tmp_path / "widget_10"
    workspace_10.mkdir()
    registry.workspaces["10"] = _workspace_entry(workspace_10)
    save_registry(store, registry)

    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: config,
    )
    monkeypatch.setattr(
        "sase.repo_inventory.read_project_local_config",
        lambda *_args, **_kwargs: {"is_sase_managed": True},
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    agents = next(record for record in inventory.records if record.name == "agents")
    expected = hidden_sidecar_clone_dir(project.project_name, "agents")
    assert agents.kind == "sidecar"
    assert agents.slug == "widget--agents"
    assert agents.description == DEFAULT_AGENTS_DESCRIPTION
    assert agents.remote_url == "git@github.com:acme/widget--agents.git"
    assert agents.path == expected
    assert agents.exists is False
    assert agents.auto_clone is False
    assert agents.env_name is None
    assert [clone.workspace_num for clone in agents.clones] == [0, 10]
    assert {clone.path for clone in agents.clones} == {expected}
    assert all(not clone.exists for clone in agents.clones)
    assert not (primary / "sase" / "repos" / "agents").exists()
    assert not (workspace_10 / "sase" / "repos" / "agents").exists()


def test_inventory_dedupes_agents_row_when_store_record_lists_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for sase-f3: an "agents" entry in the SDD store record
    (as written once the sidecar is materialized) must not produce a second,
    never-cloned "agents" row alongside the hidden machine-level one."""

    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    _set_github_origin(primary)
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
                "agents": {
                    "repo": "acme/widget--agents",
                    "remote_url": "git@github.com:acme/widget--agents.git",
                },
            },
        },
    )
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: {"is_sase_managed": True},
    )
    monkeypatch.setattr(
        "sase.repo_inventory.read_project_local_config",
        lambda *_args, **_kwargs: {"is_sase_managed": True},
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    agents_records = [record for record in inventory.records if record.name == "agents"]
    assert len(agents_records) == 1
    assert agents_records[0].path == hidden_sidecar_clone_dir(
        project.project_name, "agents"
    )


@pytest.mark.parametrize(
    "local_config",
    [
        {},
        {
            "is_sase_managed": True,
            "repos": {"sidecar": {"builtin": {"agents": {"disabled": True}}}},
        },
    ],
)
def test_inventory_omits_unmanaged_or_disabled_agents_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_config: dict[str, object],
) -> None:
    project = _project_record(tmp_path)
    monkeypatch.setattr(
        "sase.repo_inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: local_config,
    )
    monkeypatch.setattr(
        "sase.repo_inventory.read_project_local_config",
        lambda *_args, **_kwargs: local_config,
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    assert all(record.name != "agents" for record in inventory.records)


def test_inventory_scans_external_repos_across_registered_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    workspace_root = tmp_path / "managed"
    config = {"workspace": {"root": str(workspace_root)}}
    store = WorkspaceStore(str(primary), config=config)
    registry = load_registry(store)
    workspace_10 = tmp_path / "widget_10"
    workspace_10.mkdir()
    workspace_12 = tmp_path / "widget_12"
    workspace_12.mkdir()
    registry.workspaces["10"] = _workspace_entry(workspace_10)
    registry.workspaces["12"] = _workspace_entry(workspace_12)
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


def _workspace_entry(path: Path) -> WorkspaceEntry:
    return WorkspaceEntry(
        checkout_dir=str(path),
        materialization="git-clone",
        role="claim",
        created_at=1.0,
        last_used_at=1.0,
    )
