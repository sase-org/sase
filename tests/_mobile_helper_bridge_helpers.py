from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.ace.patch import Patch
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.integrations.mobile_helpers import handle_mobile_helper_bridge


def create_patch(
    name: str,
    status: str,
    project: str,
    *,
    archive: bool = False,
) -> Patch:
    suffix = "-archive" if archive else ""
    return Patch(
        name=name,
        description="",
        parent=None,
        cl=None,
        status=status,
        file_path=f"/home/user/.sase/projects/{project}/{project}{suffix}.sase",
        line_number=1,
    )


def stub_patches(
    monkeypatch: pytest.MonkeyPatch,
    patches: list[Patch],
) -> None:
    monkeypatch.setattr(
        "sase.integrations.patch_tags.find_all_patches",
        lambda: patches,
    )


def run_bridge(
    payload: object, operation: str = "changespec-tags"
) -> tuple[int, dict[str, object], str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = handle_mobile_helper_bridge(
        argparse.Namespace(mobile_helper_bridge_subcommand=operation),
        stdin=io.StringIO(json.dumps(payload)),
        stdout=stdout,
        stderr=stderr,
    )
    data = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
    return code, data, stderr.getvalue()


def seed_bead_project(root: Path) -> tuple[Path, Issue, Issue, Issue]:
    with BeadProject.init(root) as project:
        epic = project.create(
            "Alpha Epic",
            IssueType.PLAN,
            description="Alpha description",
            notes="Alpha note",
            design="plans/alpha.md",
            tier=BeadTier.EPIC,
            changespec_name="alpha_patch",
        )
        epic = project.update(epic.id, status=Status.IN_PROGRESS.value)
        phase = project.create("Alpha Phase", IssueType.PHASE, parent_id=epic.id)
        project.add_dependency(phase.id, epic.id)
        closed = project.create("Closed Epic", IssueType.PLAN)
        project.close([closed.id], reason="done")
    return root / "sdd/beads", epic, phase, closed


def seed_known_projects(
    tmp_path: Path,
    project_dirs: dict[str, Path],
    *,
    states: dict[str, str] | None = None,
) -> None:
    projects_root = tmp_path / ".sase/projects"
    for project_name, beads_dir in project_dirs.items():
        project_dir = projects_root / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        workspace = beads_dir.parents[1]
        state_line = ""
        if states and states.get(project_name):
            state_line = f"PROJECT_STATE: {states[project_name]}\n"
        (project_dir / f"{project_name}.sase").write_text(
            f"{state_line}WORKSPACE_DIR: {workspace}\n",
            encoding="utf-8",
        )
