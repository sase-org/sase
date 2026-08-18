"""Projects tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.ace.tui.modals.project_management_rendering import ProjectInventoryCounts
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult
from sase.repo_inventory import RepoInventory, RepoInventoryIssue, RepoRecord
from sase.workspace_provider.inventory import (
    WorkspaceInventory,
    WorkspaceInventoryIssue,
    WorkspaceInventoryRecord,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import project_records

_INVENTORY_NOW = 1_783_353_600.0


def _repo(
    name: str,
    kind: str,
    project: str,
    *,
    project_key: str | None = None,
    exists: bool = True,
    index: int = 0,
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project=project,
        project_key=project_key or project,
        path=f"/home/visual/work/{project}/{name}",
        exists=exists,
        auto_clone=kind != "primary",
        description=f"Visual {kind} repository {index + 1}",
        source=(
            "ProjectSpec"
            if kind == "primary"
            else "SDD store record"
            if kind == "sidecar"
            else "linked_repos config"
        ),
        env_name=None if kind == "primary" else name.upper().replace("-", "_"),
        sdd_storage="sidecar_repos" if kind == "sidecar" else None,
    )


def _workspace(
    number: int,
    project: str,
    *,
    state: str = "enabled",
    exists: bool = True,
    stale: bool = False,
    pinned: bool = False,
    claim: str | None = None,
    alive: bool | None = None,
) -> WorkspaceInventoryRecord:
    return WorkspaceInventoryRecord(
        workspace_num=number,
        project=project,
        project_key=project,
        project_state=state,
        checkout_dir=f"/home/visual/workspaces/{project}/{project}_{number}",
        exists=exists,
        materialization="git-clone",
        role="primary" if number == 0 else "claim",
        pinned=pinned,
        created_at=_INVENTORY_NOW - 35 * 86400,
        last_used_at=_INVENTORY_NOW - (31 * 86400 if stale else number * 120),
        generation=0,
        stale=stale,
        cleanup_ttl_days=14,
        registry_path=f"/home/visual/workspaces/{project}/registry.json",
        claim_agent=claim,
        claim_pid=2362714 if claim else None,
        claim_pid_alive=alive,
        claim_cl_name="projects-redesign" if claim else None,
        claim_timestamp="260706_115800" if claim else None,
    )


def _visual_repo_inventory() -> RepoInventory:
    records = (
        _repo("sase", "primary", "sase"),
        _repo("sase--plans", "sidecar", "sase", index=1),
        _repo("sase--research", "sidecar", "sase", index=2),
        _repo("sase-core", "linked", "sase", index=3),
        _repo("sase-github", "linked", "sase", exists=False, index=4),
        _repo("sase-core", "primary", "sase-core", index=5),
        _repo("sase-core--plans", "sidecar", "sase-core", index=6),
        _repo("symvision", "linked", "sase-core", index=7),
        _repo(
            "project-management-fullscreen",
            "primary",
            "project-management-fullscreen",
            index=8,
        ),
        _repo("chezmoi", "linked", "home", index=9),
        _repo("old-experiment", "primary", "old-experiment", index=10),
    )
    return RepoInventory(
        records,
        (RepoInventoryIssue("sase", "sase-github checkout is missing"),),
    )


def _visual_workspace_inventory() -> WorkspaceInventory:
    records = (
        _workspace(0, "sase", pinned=True),
        _workspace(11, "sase", claim="ace(run)-260706_115800", alive=True),
        _workspace(
            19,
            "sase",
            exists=False,
            claim="old-agent",
            alive=False,
        ),
        _workspace(42, "sase", stale=True),
        _workspace(0, "sase-core", pinned=True),
        _workspace(7, "sase-core"),
        _workspace(3, "project-management-fullscreen"),
        _workspace(5, "old-experiment", state="disabled", stale=True),
    )
    return WorkspaceInventory(
        records,
        (),
        (WorkspaceInventoryIssue("sase", "one RUNNING claim is dead"),),
    )


def _patch_project_records(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire] | None = None,
) -> None:
    """Feed the always-mounted Projects pane deterministic lifecycle records.

    Overrides the ``conftest`` autouse stub (which returns an empty list to keep
    other Admin Center snapshots deterministic) so the Projects tab renders a
    stable spread of states, claims, aliases, and warnings.
    """
    resolved = project_records() if records is None else records
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: list(resolved),
    )
    counts = {
        record.project_name: ProjectInventoryCounts(
            repo_count=3 + index % 3,
            primary_repo_count=1,
            sidecar_repo_count=1 + index % 2,
            linked_repo_count=1,
            workspace_count=(index + 1) * 2,
            claimed_workspace_count=min(record.active_claim_count, index + 1),
        )
        for index, record in enumerate(resolved)
        if record.is_project
    }
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult(counts),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: _visual_repo_inventory(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: _visual_workspace_inventory(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.time.time",
        lambda: _INVENTORY_NOW,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {},
    )


__all__ = [
    "_INVENTORY_NOW",
    "_patch_project_records",
    "_visual_repo_inventory",
    "_visual_workspace_inventory",
]
