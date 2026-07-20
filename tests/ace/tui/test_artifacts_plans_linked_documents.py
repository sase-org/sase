"""Worker loading and detail rendering for Plans-linked documents."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Markdown

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import plans_data, plans_detail
from sase.ace.tui.widgets.artifacts.plans_data import (
    LinkedPlanDocument,
    ProjectIssue,
    load_plans_snapshot,
)
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot


def _patch_project_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sdd_root: Path,
    workspace: Path,
) -> None:
    monkeypatch.setattr(
        plans_data,
        "_project_beads_dir",
        lambda _project: sdd_root / "beads",
    )
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha",
                display_name="Alpha",
                workspace_dir=str(workspace),
            ),
        ),
    )
    monkeypatch.setattr(plans_data, "_load_proposals", lambda _project, _enabled: ())
    monkeypatch.setattr(plans_data, "_load_project_archive", lambda _root: ())


@pytest.mark.parametrize(
    ("sdd_relative", "plan_relative", "reference_kind"),
    (
        ("sidecar", "202607/linked.md", "absolute"),
        ("workspace/sdd", "plans/202607/linked.md", "sdd"),
        ("workspace/.sase/sdd", "plans/202607/linked.md", "local"),
        ("sidecar", "202607/linked.md", "plans-relative"),
    ),
)
def test_snapshot_loads_reference_forms_and_phase_inheritance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sdd_relative: str,
    plan_relative: str,
    reference_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    sdd_root = tmp_path / sdd_relative
    plan_path = sdd_root / plan_relative
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        "---\ntitle: Linked plan\ntier: epic\n---\n# Linked body\n\nAll steps.\n",
        encoding="utf-8",
    )
    reference = {
        "absolute": str(plan_path),
        "sdd": "sdd/plans/202607/linked.md",
        "local": ".sase/sdd/plans/202607/linked.md",
        "plans-relative": "202607/linked.md",
    }[reference_kind]
    with BeadProject.init(sdd_root, beads_dirname="beads") as project:
        epic = project.create(
            "Linked epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=reference,
        )
        phase = project.create("Inherited phase", IssueType.PHASE, parent_id=epic.id)

    _patch_project_loaders(monkeypatch, sdd_root=sdd_root, workspace=workspace)

    snapshot = load_plans_snapshot("alpha", force=True)
    document = snapshot.linked_plan_documents[("alpha", epic.id)]

    assert document.available is True
    assert document.path == str(plan_path.resolve())
    assert document.frontmatter["title"] == "Linked plan"
    assert document.body == "# Linked body\n\nAll steps.\n"
    assert ("alpha", phase.id) not in snapshot.linked_plan_documents
    assert (
        plans_detail.linked_plan_for_issue(phase, snapshot, project="alpha") is document
    )


def test_reads_are_deduplicated_and_file_changes_invalidate_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_root = tmp_path / "sidecar"
    plan_path = sdd_root / "202607" / "linked.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# First version\n", encoding="utf-8")
    reference = "202607/linked.md"
    with BeadProject.init(sdd_root, beads_dirname="beads") as project:
        epic = project.create(
            "Linked epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=reference,
        )
        phase = project.create(
            "Direct phase",
            IssueType.PHASE,
            parent_id=epic.id,
            design=reference,
        )

    _patch_project_loaders(
        monkeypatch,
        sdd_root=sdd_root,
        workspace=tmp_path / "workspace",
    )
    reads: list[Path] = []
    original_read = plans_data._read_linked_plan_text

    def read(path: Path) -> str:
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(plans_data, "_read_linked_plan_text", read)

    first = load_plans_snapshot("alpha", force=True)
    assert reads == [plan_path.resolve()]
    assert first.linked_plan_documents[("alpha", phase.id)].body == "# First version\n"

    unchanged = load_plans_snapshot("alpha", previous=first)
    assert unchanged is first
    assert reads == [plan_path.resolve()]

    plan_path.write_text("# Second version with new content\n", encoding="utf-8")
    changed = load_plans_snapshot("alpha", previous=first)
    assert changed is not first
    assert changed.linked_plan_documents[("alpha", epic.id)].body.startswith(
        "# Second version"
    )
    assert reads == [plan_path.resolve(), plan_path.resolve()]


def test_failures_are_isolated_and_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_root = tmp_path / "sidecar"
    good_path = sdd_root / "202607" / "good.md"
    unreadable_path = sdd_root / "202607" / "unreadable.md"
    good_path.parent.mkdir(parents=True)
    good_path.write_text("# Good plan\n", encoding="utf-8")
    unreadable_path.write_text("# Hidden plan\n", encoding="utf-8")
    with BeadProject.init(sdd_root, beads_dirname="beads") as project:
        good = project.create(
            "Good epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design="202607/good.md",
        )
        missing = project.create(
            "Missing epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design="202607/missing.md",
        )
        unreadable = project.create(
            "Unreadable epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design="202607/unreadable.md",
        )

    _patch_project_loaders(
        monkeypatch,
        sdd_root=sdd_root,
        workspace=tmp_path / "workspace",
    )
    original_read = plans_data._read_linked_plan_text

    def read(path: Path) -> str:
        if path == unreadable_path.resolve():
            raise PermissionError("host-specific detail")
        return original_read(path)

    monkeypatch.setattr(plans_data, "_read_linked_plan_text", read)

    snapshot = load_plans_snapshot("alpha", force=True)

    assert snapshot.linked_plan_documents[("alpha", good.id)].body == "# Good plan\n"
    assert snapshot.linked_plan_documents[("alpha", missing.id)].error == (
        "Linked plan unavailable: file not found."
    )
    assert snapshot.linked_plan_documents[("alpha", unreadable.id)].error == (
        "Linked plan unavailable: file could not be read."
    )
    assert snapshot.errors == {}


def test_malformed_reference_is_unavailable_without_a_filesystem_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = pytest.fail
    monkeypatch.setattr(plans_data, "_read_linked_plan_text", read)

    document = plans_data._load_linked_plan_document(
        "bad\x00reference",
        workspace_dir=str(tmp_path / "workspace"),
        plans_root=tmp_path / "plans",
        read_cache={},
    )

    assert document.error == "Linked plan unavailable: invalid reference."
    assert document.path == ""


async def test_bead_details_append_current_plan_after_description_and_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    epic = replace(
        snapshot.epics[0].issue,
        design="202607/linked.md",
        notes="Epic notes stay before the plan.",
    )
    first_phase = replace(
        snapshot.phases_by_epic[("alpha", epic.id)][0].issue,
        description="Phase description stays first.",
        notes="Phase notes stay second.",
    )
    phases = (
        ProjectIssue("alpha", first_phase),
        snapshot.phases_by_epic[("alpha", epic.id)][1],
    )
    document = LinkedPlanDocument(
        reference=epic.design,
        path=str(tmp_path / "202607" / "linked.md"),
        content=(
            "---\ntitle: Worker-loaded plan\ngoal: Preserve ordering\n---\n"
            "# Linked plan body\n\nComplete content.\n"
        ),
        frontmatter={
            "title": "Worker-loaded plan",
            "goal": "Preserve ordering",
            "phases": "small: small · medium: medium · large: large",
        },
        body="# Linked plan body\n\nComplete content.\n",
        error=None,
        signature=(1, 1, 1, 1),
    )
    snapshot = replace(
        snapshot,
        epics=(ProjectIssue("alpha", epic),),
        phases_by_epic={("alpha", epic.id): phases},
        linked_plan_documents={("alpha", epic.id): document},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("[")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        detail = pane.query_one("#plans-detail", Markdown)

        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "proposal"  # type: ignore[union-attr]
        assert "## Plan" not in detail.source

        await page.press("j")
        pane._update_detail()
        epic_source = detail.source
        assert epic_source.index("## Description") < epic_source.index("## Notes")
        assert epic_source.index("## Notes") < epic_source.index("## Plan")
        assert "**Title:** Worker-loaded plan" in epic_source
        assert epic_source.count("small: small · medium: medium · large: large") == 1
        assert "# Linked plan body" in epic_source

        await page.press("l", "j")
        pane._update_detail()
        phase_source = detail.source
        assert phase_source.index("Phase description") < phase_source.index(
            "Phase notes"
        )
        assert phase_source.index("Phase notes") < phase_source.index("## Plan")
        assert phase_source.count("# Linked plan body") == 1

        pane._snapshot = replace(snapshot, linked_plan_documents={})
        pane._update_detail()
        assert "## Plan" not in detail.source
        assert "# Linked plan body" not in detail.source

        pane._snapshot = snapshot
        await page.press("G")
        pane._update_detail()
        assert pane.selected_row() is not None
        assert pane.selected_row().kind == "archive"  # type: ignore[union-attr]
        assert detail.source == "# Rollout\n\nDone."
        assert "## Plan" not in detail.source
