"""Cross-project workspace inventory coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.running_field import WorkspaceClaim
from sase.workspace_provider.inventory import collect_workspace_inventory
from sase.workspace_provider.registry import (
    load_or_init_registry,
    record_workspace,
    registry_path,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore


def _project(
    tmp_path: Path,
    name: str,
    *,
    state: str = "enabled",
) -> ProjectRecordWire:
    primary = tmp_path / "primary" / name
    primary.mkdir(parents=True)
    project_dir = tmp_path / "projects" / name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(name, encoding="utf-8")
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(primary),
        state=state,
        state_explicit=state == "disabled",
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled",
        display_name=name,
        is_project=True,
        vcs_kind="git",
    )


def _config(tmp_path: Path, primary: str) -> dict[str, object]:
    return {
        "workspace": {
            "root": str(tmp_path / "managed"),
            "project_key": Path(primary).name,
            "cleanup_ttl_days": 1,
        }
    }


def test_inventory_joins_claims_staleness_missing_and_disabled_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = _project(tmp_path, "enabled")
    disabled = _project(tmp_path, "disabled", state="disabled")
    corrupt = _project(tmp_path, "corrupt")
    projects = [enabled, disabled, corrupt]

    def config_for(primary: str, _config: object) -> dict[str, object]:
        return _config_for(primary)

    def _config_for(primary: str) -> dict[str, object]:
        return _config(tmp_path, primary)

    for project in projects:
        primary = project.workspace_dir or ""
        store = WorkspaceStore(primary, config=_config_for(primary), env={})
        if project is corrupt:
            Path(store.root_dir).mkdir(parents=True)
            Path(registry_path(store.root_dir)).write_text(
                json.dumps(
                    {
                        "workspaces": {
                            "10": {
                                "created_at": "invalid timestamp",
                                "last_used_at": 1,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            continue
        registry = load_or_init_registry(store)
        save_registry(store, registry)

    enabled_store = WorkspaceStore(
        enabled.workspace_dir or "",
        config=_config_for(enabled.workspace_dir or ""),
        env={},
    )
    claimed_path = enabled_store.resolve(10)
    Path(claimed_path.checkout_dir).mkdir(parents=True)
    record_workspace(enabled_store, claimed_path, role="claim")
    stale_path = enabled_store.resolve(11)
    registry = record_workspace(enabled_store, stale_path, role="claim")
    registry.workspaces["11"].last_used_at = 10.0
    save_registry(enabled_store, registry)

    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_project_records",
        lambda *_args, **_kwargs: projects,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.inventory.resolution_config",
        config_for,
    )

    def claims(content: str) -> list[WorkspaceClaim]:
        if content == "enabled":
            return [
                WorkspaceClaim(
                    workspace_num=0,
                    workflow="deferred-a",
                    cl_name=None,
                    pid=1001,
                ),
                WorkspaceClaim(
                    workspace_num=0,
                    workflow="deferred-b",
                    cl_name=None,
                    pid=1002,
                ),
                WorkspaceClaim(
                    workspace_num=10,
                    workflow="ace(run)-260713_120000",
                    cl_name="enabled_change",
                    pid=1234,
                    artifacts_timestamp="260713_120000",
                ),
            ]
        return []

    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_workspace_claims_from_content",
        claims,
    )

    inventory = collect_workspace_inventory(
        include_disabled=True,
        now=200_000.0,
        process_running=lambda pid: pid == 1234,
    )

    enabled_rows = {
        record.workspace_num: record
        for record in inventory.records
        if record.project == "enabled"
    }
    assert enabled_rows[10].claim_agent == "ace(run)-260713_120000"
    assert enabled_rows[10].claim_pid_alive is True
    assert enabled_rows[10].stale is False
    assert enabled_rows[11].stale is True
    assert enabled_rows[11].exists is False
    assert any(record.project == "disabled" for record in inventory.records)
    assert not any(record.project == "corrupt" for record in inventory.records)
    assert any(
        issue.project == "corrupt"
        and "Unable to read workspace registry" in issue.message
        for issue in inventory.issues
    )
    assert not any(
        "Multiple RUNNING claims reference workspace #0" in issue.message
        for issue in inventory.issues
    )


def test_inventory_reports_live_numbered_cwd_without_matching_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "proj")
    primary = project.workspace_dir or ""
    store = WorkspaceStore(primary, config=_config(tmp_path, primary), env={})
    registry = load_or_init_registry(store)
    save_registry(store, registry)
    claimed_path = store.resolve(10)
    checkout = Path(claimed_path.checkout_dir.rstrip("/"))
    checkout.mkdir(parents=True)
    record_workspace(store, claimed_path, role="claim")

    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.inventory.resolution_config",
        lambda *_args, **_kwargs: _config(tmp_path, primary),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_workspace_claims_from_content",
        lambda _content: [
            WorkspaceClaim(0, "ace(run)-260814_120000", "proj", pid=1234)
        ],
    )

    inventory = collect_workspace_inventory(
        now=100.0,
        process_running=lambda pid: pid == 1234,
        process_cwd=lambda pid: str(checkout) if pid == 1234 else None,
    )

    row = next(record for record in inventory.records if record.workspace_num == 10)
    assert row.claimed is False
    assert row.cwd_occupant_pids == (1234,)
    assert row.cwd_occupant_agents == ("ace(run)-260814_120000",)
    issue = next(
        issue
        for issue in inventory.issues
        if issue.code == "unclaimed_occupied_workspace"
    )
    assert "Workspace #10 is occupied" in issue.message
    assert "PID 1234" in issue.message


def test_inventory_reports_double_occupied_numbered_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, "proj")
    primary = project.workspace_dir or ""
    store = WorkspaceStore(primary, config=_config(tmp_path, primary), env={})
    registry = load_or_init_registry(store)
    save_registry(store, registry)
    claimed_path = store.resolve(10)
    checkout = Path(claimed_path.checkout_dir.rstrip("/"))
    checkout.mkdir(parents=True)
    record_workspace(store, claimed_path, role="claim")

    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_project_records",
        lambda *_args, **_kwargs: [project],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.inventory.resolution_config",
        lambda *_args, **_kwargs: _config(tmp_path, primary),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.inventory.list_workspace_claims_from_content",
        lambda _content: [
            WorkspaceClaim(10, "ace(run)-260814_120000", "proj", pid=1234),
            WorkspaceClaim(0, "ace(run)-260814_120001", "proj", pid=5678),
        ],
    )

    inventory = collect_workspace_inventory(
        now=100.0,
        process_running=lambda pid: pid in {1234, 5678},
        process_cwd=lambda pid: str(checkout) if pid in {1234, 5678} else None,
    )

    row = next(record for record in inventory.records if record.workspace_num == 10)
    assert row.claim_pid == 1234
    assert row.cwd_occupant_pids == (1234, 5678)
    issue = next(
        issue for issue in inventory.issues if issue.code == "double_occupied_workspace"
    )
    assert "Multiple live agent processes" in issue.message
    assert "PID 1234" in issue.message
    assert "PID 5678" in issue.message
