"""Shared helpers for ``sase bead work`` CLI tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject


class FakeLaunchResult:
    def __init__(self) -> None:
        self.pid = 4242
        self.workspace_num = 7
        self.workspace_dir = "/tmp/fake_workspace"
        self.output_path = "/tmp/fake_output"


def epic_clan_declaration(epic_id: str) -> str:
    return f"%clan({epic_id}, tribe=epic, summary_script=sase_clan_summary_epic)"


def bead_wait_lines(rendered: str) -> list[str]:
    return [line for line in rendered.splitlines() if line.startswith("%w(bead=")]


def seed_diamond(project_dir: Path) -> tuple[str, list[str]]:
    """Seed a diamond DAG: p1 -> {p2, p3} -> p4. Returns (epic_id, phase_ids)."""
    with BeadProject(project_dir) as proj:
        epic = proj.create("Diamond epic", IssueType.PLAN)
        p1 = proj.create("P1", IssueType.PHASE, parent_id=epic.id)
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
        p3 = proj.create("P3", IssueType.PHASE, parent_id=epic.id)
        p4 = proj.create("P4", IssueType.PHASE, parent_id=epic.id)
        proj.add_dependency(p2.id, p1.id)
        proj.add_dependency(p3.id, p1.id)
        proj.add_dependency(p4.id, p2.id)
        proj.add_dependency(p4.id, p3.id)
        return epic.id, [p1.id, p2.id, p3.id, p4.id]


def seed_patch_epic(project_dir: Path) -> tuple[str, list[str]]:
    with BeadProject(project_dir) as proj:
        epic = proj.create(
            "Patch epic",
            IssueType.PLAN,
            changespec_name="feature_epic",
            changespec_bug_id="12345",
        )
        p1 = proj.create("P1", IssueType.PHASE, parent_id=epic.id)
        p2 = proj.create("P2", IssueType.PHASE, parent_id=epic.id)
        proj.add_dependency(p2.id, p1.id)
        return epic.id, [p1.id, p2.id]


def make_args(
    target: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    yes_to_all: bool = False,
    no_push: bool = False,
    json_output: bool = False,
    launch_feedback: str | None = None,
) -> Any:
    return argparse.Namespace(
        target=target,
        dry_run=dry_run,
        json=json_output,
        yes=yes,
        yes_to_all=yes_to_all,
        no_push=no_push,
        launch_feedback=launch_feedback,
    )


def seed_task(
    project_dir: Path,
    *,
    status: Status = Status.READY,
    assignee: str = "",
    size: PhaseSize | None = PhaseSize.SMALL,
) -> str:
    """Create one task bead with the requested launch state."""
    with BeadProject(project_dir) as proj:
        task = proj.create("Standalone task", IssueType.TASK, size=size)
        if status is Status.CLOSED:
            proj.close([task.id])
        elif status is not Status.OPEN or assignee:
            proj.update(
                task.id,
                status=status.value,
                assignee=assignee,
            )
        return task.id


def write_orphan_meta(home: Path, name: str, *, done: bool = False) -> Path:
    """Write a fake live agent_meta.json under ``home/.sase/projects/...``."""
    artifact_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / f"orphan-{name}"
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": name, "pid": os.getpid(), "model": "test"})
    )
    if done:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": "failed"}))
    return artifact_dir


def write_bead_agent_meta(
    home: Path,
    name: str,
    *,
    bead_id: str,
    done: bool = False,
    waiting: bool = False,
    outcome: str = "failed",
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
) -> Path:
    """Write a fake bead-associated agent artifact under ``home``."""
    artifact_dir = (
        home
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / f"bead-{name.replace('/', '-')}"
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, Any] = {
        "name": name,
        "pid": os.getpid(),
        "model": "test",
        "bead_id": bead_id,
    }
    if "." in bead_id:
        meta["phase_bead_id"] = bead_id
        meta["epic_bead_id"] = bead_id.rsplit(".", 1)[0]
    else:
        meta["epic_bead_id"] = bead_id
    if agent_family:
        meta["agent_family"] = agent_family
    if agent_family_role:
        meta["agent_family_role"] = agent_family_role
    if agent_clan:
        meta["agent_clan"] = agent_clan
        meta["agent_clan_generation"] = agent_clan_generation or artifact_dir.name
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if waiting:
        (artifact_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["upstream"]}), encoding="utf-8"
        )
    if done:
        (artifact_dir / "done.json").write_text(
            json.dumps({"outcome": outcome}), encoding="utf-8"
        )
    return artifact_dir
