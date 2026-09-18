from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from tests._conftest_environment import redirect_sase_home


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BeadProject:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    return BeadProject.init(tmp_path)


def test_bead_link_event_round_trip_and_related_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    left = project.create("Left", IssueType.PLAN)
    right = project.create("Right", IssueType.PLAN)
    added = project.add_link(
        left.id,
        f"bead:{right.id}",
        "related",
        "shares the ACE-TUI flake root cause",
    )
    reverse = project.add_link(
        right.id,
        f"bead:{left.id}",
        "related",
        "shares the ACE-TUI flake root cause",
    )
    reloaded = project.show(left.id)

    assert added.links[0].target_ref == f"bead:{right.id}"
    assert reverse.links == []
    assert len(reloaded.links) == 1
    assert reloaded.links[0].description == "shares the ACE-TUI flake root cause"
    events = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project.beads_dir / "events").rglob("*.jsonl")
    )
    assert "link_added" in events


def test_bead_link_remove_event_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    left = project.create("Left", IssueType.PLAN)
    right = project.create("Right", IssueType.PLAN)
    project.add_link(
        left.id,
        f"bead:{right.id}",
        "related",
        "shares the ACE-TUI flake root cause",
    )
    removed = project.remove_link(left.id, f"bead:{right.id}", relation="related")
    reloaded = project.show(left.id)

    assert removed.links == []
    assert reloaded.links == []
    events = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project.beads_dir / "events").rglob("*.jsonl")
    )
    assert "link_added" in events
    assert "link_removed" in events


def test_set_bead_endpoint_projections_converts_row_requests_to_core_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.sdd.artifact_link_beads import set_bead_endpoint_projections

    project = _project(tmp_path, monkeypatch)
    issue = project.create("Target", IssueType.PLAN)
    captured: list[object] = []

    def _fake_batch(beads_dir: Path, requests: object) -> dict[str, object]:
        captured.append((beads_dir, list(requests)))
        return {"operation": "link_project", "changed": True, "issue_ids": [issue.id]}

    monkeypatch.setattr(
        "sase.core.bead_mutation_facade.set_link_projections", _fake_batch
    )

    outcome = set_bead_endpoint_projections(
        project.beads_dir,
        (
            {
                "issue_id": issue.id,
                "target_ref": "plan:202609/a.md",
                "relation": "related",
                "direction": "out",
                "operation_id": "a" * 32,
                "row": {
                    "description": "present edge",
                    "origin": "manual",
                    "uses": 2,
                },
                "now": "2026-01-01T00:01:00Z",
            },
            {
                "issue_id": issue.id,
                "target_ref": "plan:202609/a.md",
                "relation": "related",
                "direction": "out",
                "operation_id": "b" * 32,
                "row": None,
                "now": "2026-01-01T00:02:00Z",
            },
        ),
    )

    assert outcome["changed"] is True
    _beads_dir, requests = captured[0]
    assert _beads_dir == project.beads_dir
    assert requests == [
        {
            "issue_id": issue.id,
            "target_ref": "plan:202609/a.md",
            "relation": "related",
            "direction": "out",
            "present": True,
            "operation_id": "a" * 32,
            "now": "2026-01-01T00:01:00Z",
            "description": "present edge",
            "origin": "manual",
            "uses": 2,
        },
        {
            "issue_id": issue.id,
            "target_ref": "plan:202609/a.md",
            "relation": "related",
            "direction": "out",
            "present": False,
            "operation_id": "b" * 32,
            "now": "2026-01-01T00:02:00Z",
        },
    ]


def test_reserved_relation_points_at_bead_dep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    left = project.create("Left", IssueType.PLAN)
    right = project.create("Right", IssueType.PLAN)
    with pytest.raises(ValueError, match="sase bead dep"):
        project.add_link(left.id, f"bead:{right.id}", "blocks", "scheduling")
