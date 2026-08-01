"""Integration coverage for Plans bead-link and document loading."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.artifacts.plans_data import load_plans_snapshot
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject


def test_snapshot_reads_beads_only_to_partition_plan_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = tmp_path / "alpha--plans"
    month = plans_root / "202608"
    month.mkdir(parents=True)
    active_path = month / "active.md"
    active_path.write_text(
        "---\ntitle: Active plan\ntier: epic\nstatus: wip\n---\nActive body.\n",
        encoding="utf-8",
    )
    (month / "archived.md").write_text(
        "---\ntitle: Archived plan\ntier: epic\nstatus: done\n---\nArchived body.\n",
        encoding="utf-8",
    )
    with BeadProject.init(plans_root, beads_dirname="beads") as project:
        epic = project.create(
            "Fixture epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design="plans:202608/active.md",
        )
        project.create("Fixture phase", IssueType.PHASE, parent_id=epic.id)

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_beads_dir",
        lambda _project: plans_root / "beads",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_data._project_document_roots",
        lambda _project: {"plans": plans_root},
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

    assert [(item.owner.bead_id, item.document.path) for item in snapshot.active] == [
        (epic.id, str(active_path))
    ]
    assert [item.match.plan.title for item in snapshot.archive] == ["Archived"]
    assert not hasattr(snapshot, "phases_by_epic")
