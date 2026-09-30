"""Sidecar-configuration tests for the repo inventory.

Split from ``tests.test_repo_inventory``; the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._linked_repo_config import (
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
)
from sase.linked_repos import hidden_sidecar_clone_dir
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.store import write_sdd_store_record
from sase.workspace_provider.registry import load_registry, save_registry
from sase.workspace_provider.store import WorkspaceStore
from tests._repo_inventory_helpers import (
    project_record,
    set_github_origin,
    workspace_entry,
)

__all__ = [
    "test_disabled_configured_sidecar_suppresses_store_record",
    "test_inventory_dedupes_agents_row_when_store_record_lists_it",
    "test_inventory_defaults_beads_lazy_and_plans_eager_without_explicit_config",
    "test_inventory_exposes_hidden_agents_at_one_machine_level_path",
    "test_inventory_exposes_hidden_attachments_private_at_machine_level_path",
    "test_inventory_gates_beads_auto_clone_on_store_record",
    "test_inventory_omits_unmanaged_or_disabled_agents_sidecar",
    "test_pinned_sidecar_identity_overrides_stale_store_repo",
]


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
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
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


def test_inventory_defaults_beads_lazy_and_plans_eager_without_explicit_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/plans",
                    "remote_url": "git@example.test:acme/plans.git",
                },
                "beads": {
                    "repo": "acme/beads",
                    "remote_url": "git@example.test:acme/beads.git",
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
        lambda *_args, **_kwargs: {},
    )

    inventory = collect_repo_inventory(tmp_path / "projects")

    plans = next(record for record in inventory.records if record.name == "plans")
    beads = next(record for record in inventory.records if record.name == "beads")
    assert plans.auto_clone is True
    assert beads.auto_clone is False


def test_disabled_configured_sidecar_suppresses_store_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
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
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
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


def test_inventory_exposes_hidden_agents_at_one_machine_level_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    config = {"workspace": {"root": str(tmp_path / "managed")}}
    store = WorkspaceStore(str(primary), config=config)
    registry = load_registry(store)
    workspace_10 = tmp_path / "widget_10"
    workspace_10.mkdir()
    registry.workspaces["10"] = workspace_entry(workspace_10)
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


def test_inventory_exposes_hidden_attachments_private_at_machine_level_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    config = {"workspace": {"root": str(tmp_path / "managed")}}
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

    store = next(
        record for record in inventory.records if record.name == "attachments-private"
    )
    expected = hidden_sidecar_clone_dir(project.project_name, "attachments-private")
    assert store.kind == "sidecar"
    assert store.slug == "widget--attachments-private"
    assert store.description == DEFAULT_ATTACHMENTS_PRIVATE_DESCRIPTION
    assert store.remote_url == ("git@github.com:acme/widget--attachments-private.git")
    assert store.path == expected
    assert store.exists is False
    assert store.auto_clone is False
    assert store.env_name is None
    assert not (primary / "sase" / "repos" / "attachments-private").exists()


def test_inventory_dedupes_agents_row_when_store_record_lists_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test for sase-f3: an "agents" entry in the SDD store record
    (as written once the sidecar is materialized) must not produce a second,
    never-cloned "agents" row alongside the hidden machine-level one."""

    project = project_record(tmp_path)
    primary = Path(project.workspace_dir or "")
    set_github_origin(primary)
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
    project = project_record(tmp_path)
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
