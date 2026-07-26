"""Tests for canonical bead-store status lookups."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead.store_locator import bead_statuses_for_project


def test_bead_statuses_for_project_reads_requested_ids_from_canonical_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        closed = project.create("Closed", IssueType.PLAN)
        claimed = project.create("Claimed", IssueType.PLAN)
        project.update(closed.id, status="closed")
        project.update(claimed.id, status="claimed")

    beads_dir = tmp_path / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [beads_dir] if project == "known" else [],
    )

    assert bead_statuses_for_project(
        "known",
        [closed.id, claimed.id, "missing", closed.id],
    ) == {
        closed.id: "closed",
        claimed.id: "claimed",
    }
    assert bead_statuses_for_project("unknown", [closed.id]) is None
