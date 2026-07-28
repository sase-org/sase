"""Data-loading coverage for the Artifacts Plans pane."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.artifacts.plans_data import load_plans_snapshot
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject


def test_snapshot_reads_fixture_bead_dag_and_flat_plan_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = tmp_path / "alpha--plans"
    with BeadProject.init(plans_root, beads_dirname="beads") as project:
        epic = project.create(
            "Fixture epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            description="Fixture description",
        )
        first = project.create("First phase", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Second phase", IssueType.PHASE, parent_id=epic.id)
        project.add_dependency(second.id, first.id)

    month = plans_root / "202607"
    month.mkdir()
    (month / "fixture.md").write_text(
        "---\ntier: epic\nstatus: wip\ncreate_time: 2026-07-15 12:00:00\n---\n"
        "# Fixture archive\n\nRendered body.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_beads_dir",
        lambda _project: plans_root / "beads",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_plans_root",
        lambda _project: plans_root,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha",
                display_name="Alpha",
                workspace_dir=str(tmp_path / "workspace"),
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._load_proposals",
        lambda _project, _enabled: (),
    )

    snapshot = load_plans_snapshot("alpha", force=True)

    assert [row.issue.id for row in snapshot.epics] == [epic.id]
    assert [row.issue.id for row in snapshot.phases_by_epic[("alpha", epic.id)]] == [
        first.id,
        second.id,
    ]
    assert ("alpha", first.id) in snapshot.ready_ids
    assert ("alpha", second.id) in snapshot.blocked_ids
    assert [entry.match.plan.title for entry in snapshot.archive] == ["Fixture archive"]
