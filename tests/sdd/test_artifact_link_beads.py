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


def test_reserved_relation_points_at_bead_dep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, monkeypatch)
    left = project.create("Left", IssueType.PLAN)
    right = project.create("Right", IssueType.PLAN)
    with pytest.raises(ValueError, match="sase bead dep"):
        project.add_link(left.id, f"bead:{right.id}", "blocks", "scheduling")
