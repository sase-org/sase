"""Shared helpers for SDD commit tests."""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from sase.sdd.store import SddStore, write_sdd_store_record


def init_test_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


@dataclass(frozen=True)
class SidecarWorkspaceTopology:
    """Primary metadata plus workspace-local sidecar clone paths."""

    primary: Path
    workspace: Path
    plans: Path
    research: Path
    beads: Path
    store: SddStore


def make_sidecar_workspace_topology(
    root: Path,
    *,
    owner: str = "acme",
    project: str = "project",
    workspace_num: int = 7,
) -> SidecarWorkspaceTopology:
    """Build the production primary/numbered-workspace sidecar topology."""

    primary = root / "primary" / project
    workspace = root / "workspaces" / f"{project}_{workspace_num}"
    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    beads = workspace / "sase" / "repos" / "beads"
    primary.mkdir(parents=True)
    marker_dir = workspace / ".sase"
    marker_dir.mkdir(parents=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "primary_workspace_dir": str(primary),
                "project_key": project,
                "project_name": project,
                "registry_path": str(primary / ".sase" / "registry.json"),
                "schema_version": 1,
                "workspace_num": workspace_num,
            }
        ),
        encoding="utf-8",
    )

    repo_prefix = f"{owner}/{project}"
    remote_prefix = f"git@example.com:{repo_prefix}"
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                kind: {
                    "repo": f"{repo_prefix}--{kind}",
                    "remote_url": f"{remote_prefix}--{kind}.git",
                }
                for kind in ("plans", "research", "beads")
            },
        },
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=f"{remote_prefix}--plans.git",
        research_dir=research,
        research_remote_url=f"{remote_prefix}--research.git",
        beads_dir=beads,
        beads_remote_url=f"{remote_prefix}--beads.git",
    )
    return SidecarWorkspaceTopology(
        primary=primary,
        workspace=workspace,
        plans=plans,
        research=research,
        beads=beads,
        store=store,
    )
