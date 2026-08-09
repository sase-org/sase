"""Tests for BeadProject initialization and storage behavior."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sase.bead.config import load_config, save_config
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject


def test_init_creates_beads_dir(tmp_path):
    with BeadProject.init(tmp_path):
        assert (tmp_path / "sdd/beads").is_dir()
        assert (tmp_path / "sdd/beads" / "config.json").exists()
        assert (tmp_path / "sdd/beads" / "beads.db").exists()
        assert (tmp_path / "sdd/beads" / "issues.jsonl").exists()


def test_root_level_store_round_trip(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Root-level plan", IssueType.PLAN)
        assert project.root_dir == tmp_path
        assert project.beads_dir == tmp_path

    assert (tmp_path / "config.json").is_file()
    assert (tmp_path / "issues.jsonl").is_file()
    assert (tmp_path / "beads.db").is_file()
    with BeadProject(tmp_path, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        assert project.show(issue.id).title == "Root-level plan"


def test_init_already_exists(tmp_path):
    with BeadProject.init(tmp_path):
        pass
    # Second init should succeed without error
    with BeadProject.init(tmp_path) as proj:
        assert proj is not None


def test_constructor_raises_without_beads_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        BeadProject(tmp_path)


def test_read_commands_do_not_open_compatibility_mirror(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        child = project.create("Child", IssueType.PHASE, parent_id=epic.id)

    db_path = tmp_path / "sdd/beads/beads.db"
    for suffix in ("", "-shm", "-wal"):
        candidate = db_path.parent / f"{db_path.name}{suffix}"
        if candidate.exists():
            candidate.unlink()

    with BeadProject(tmp_path) as project:
        assert project.show(epic.id).id == epic.id
        assert [issue.id for issue in project.list_issues()] == [epic.id, child.id]
        assert [issue.id for issue in project.get_epic_children(epic.id)] == [child.id]
        assert not db_path.exists()

        assert project._max_local_child_counter(epic.id) == 1
        assert db_path.exists()


def test_cold_large_jsonl_store_reads_without_building_mirror(tmp_path: Path) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    (beads_dir / "config.json").write_text(
        json.dumps(
            {
                "issue_prefix": "perf",
                "next_counter": 1501,
                "owner": "owner@example.com",
            }
        ),
        encoding="utf-8",
    )
    epic = {
        "id": "perf-1",
        "title": "Large epic",
        "status": "open",
        "issue_type": "plan",
        "tier": "epic",
        "parent_id": None,
        "created_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-18T00:00:00Z",
        "dependencies": [],
    }
    children = [
        {
            "id": f"perf-1.{index}",
            "title": f"Child {index}",
            "status": "open",
            "issue_type": "phase",
            "parent_id": "perf-1",
            "created_at": "2026-07-18T00:00:00Z",
            "updated_at": "2026-07-18T00:00:00Z",
            "dependencies": [],
        }
        for index in range(1, 1500)
    ]
    (beads_dir / "issues.jsonl").write_text(
        "\n".join(json.dumps(issue) for issue in [epic, *children]) + "\n",
        encoding="utf-8",
    )
    db_path = beads_dir / "beads.db"

    with BeadProject(tmp_path, beads_dirname="beads") as project:
        assert project.show("perf-1.1499").title == "Child 1499"
        assert len(project.get_epic_children("perf-1")) == 1499
        assert len(project.list_issues()) == 1500
        assert not db_path.exists()

        assert project._max_local_child_counter("perf-1") == 1499
        assert db_path.exists()
        row = project._conn.execute("SELECT COUNT(*) FROM issues").fetchone()
        assert row is not None
        assert row[0] == 1500


def test_doctor_clean(project):
    messages = project.doctor()
    assert any("OK" in m for m in messages)


def test_doctor_detects_orphan(project):
    """Create a legacy JSONL child whose parent doesn't exist."""
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)

    jsonl_path = project.beads_dir / "issues.jsonl"
    rows = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    jsonl_path.write_text(
        "\n".join(
            json.dumps(row, separators=(",", ":"))
            for row in rows
            if row["id"] == child.id
        )
        + "\n"
    )
    shutil.rmtree(project.beads_dir / "events")

    messages = project.doctor()
    assert any("orphan" in m.lower() for m in messages)


def test_jsonl_persisted_after_create(project):
    project.create("Epic", IssueType.PLAN)
    jsonl = (project.beads_dir / "issues.jsonl").read_text()
    assert "Epic" in jsonl


def test_counter_persists_across_instances(tmp_path):
    with BeadProject.init(tmp_path) as proj1:
        proj1.create("E1", IssueType.PLAN)
        proj1.create("E2", IssueType.PLAN)

    # Open a new instance
    with BeadProject(tmp_path) as proj2:
        proj2.create("E3", IssueType.PLAN)
        # Should not reuse IDs
        all_ids = [i.id for i in proj2.list_issues()]
        assert len(all_ids) == len(set(all_ids))


def test_create_uses_local_counter_when_sibling_has_allocations(
    tmp_path: Path,
) -> None:
    workspace_a = tmp_path / "sase"
    workspace_b = tmp_path / "sase_101"
    _init_project_with_config(workspace_a, next_counter=1)
    _init_project_with_config(workspace_b, next_counter=1)

    with BeadProject(workspace_a) as project_a:
        assert project_a.create("A", IssueType.PLAN).id == "sase-1"

    with BeadProject(workspace_b) as project_b:
        issue = project_b.create("B", IssueType.PLAN)

    assert issue.id == "sase-1"
    assert load_config(workspace_b / "sdd/beads")["next_counter"] == 2


def test_create_keeps_local_counter_when_config_is_ahead(
    tmp_path: Path,
) -> None:
    workspace_a = tmp_path / "sase"
    workspace_b = tmp_path / "sase_101"
    _init_project_with_config(workspace_a, next_counter=1)
    _init_project_with_config(workspace_b, next_counter=10)

    with BeadProject(workspace_a) as project_a:
        assert project_a.create("A", IssueType.PLAN).id == "sase-1"

    with BeadProject(workspace_b) as project_b:
        issue = project_b.create("B", IssueType.PLAN)

    assert issue.id == "sase-a"
    assert load_config(workspace_b / "sdd/beads")["next_counter"] == 11


def test_create_child_uses_local_child_counter(tmp_path: Path) -> None:
    workspace_a = tmp_path / "sase"
    workspace_b = tmp_path / "sase_101"
    _init_project_with_config(workspace_a, next_counter=1)
    _init_project_with_config(workspace_b, next_counter=1)

    with BeadProject(workspace_a) as project_a:
        parent_a = project_a.create("Parent", IssueType.PLAN)
        assert (
            project_a.create("A child", IssueType.PHASE, parent_id=parent_a.id).id
            == "sase-1.1"
        )

    with BeadProject(workspace_b) as project_b:
        parent_b = project_b.create("Parent", IssueType.PLAN)
        assert parent_b.id == "sase-1"

    with BeadProject(workspace_b) as project_b:
        child = project_b.create("B child", IssueType.PHASE, parent_id="sase-1")

    assert child.id == "sase-1.1"


def _init_project_with_config(root: Path, *, next_counter: int) -> None:
    with BeadProject.init(root):
        pass
    save_config(
        root / "sdd/beads",
        {"issue_prefix": "sase", "next_counter": next_counter, "owner": ""},
    )
