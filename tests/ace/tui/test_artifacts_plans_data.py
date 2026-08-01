"""Data-loading contracts for the document-only Plans snapshot."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.artifacts import plans_data
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.plans_data import LinkedPlanDocument
from sase.bead.model import BeadTier, IssueType, Status
from sase.plan_search.model import Plan, PlanSearchMatch


def _match(path: Path, title: str, *, status: str = "wip") -> PlanSearchMatch:
    return PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(path),
            relpath=f"202608/{path.name}",
            name=path.stem,
            title=title,
            status=status,
            created_at="2026-08-01 10:00:00",
            prompt_link="",
            summary="",
            body=f"{title} body",
            frontmatter={"tier": "epic", "status": status},
        ),
        matched_fields=[],
        score=1.0,
    )


def test_proposal_document_projects_all_frontmatter_and_strips_body() -> None:
    frontmatter, body = plans_data._parse_proposal_document(  # noqa: SLF001
        "---\ntitle: Example\nphases:\n- one\n- two\nflag: true\n---\nBody\n"
    )

    assert frontmatter == {
        "title": "Example",
        "phases": "one, two",
        "flag": "true",
    }
    assert body == "Body\n"


def test_snapshot_partitions_live_linked_documents_from_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_path = tmp_path / "202608" / "active.md"
    archived_path = tmp_path / "202608" / "archived.md"
    link = BeadPlanLink(
        "alpha",
        "alpha-1",
        IssueType.PLAN,
        Status.IN_PROGRESS,
        BeadTier.EPIC,
        "Active plan",
        "2026-08-01T09:00:00Z",
        "plans:202608/active.md",
        str(active_path),
    )
    document = LinkedPlanDocument(
        link.reference,
        str(active_path),
        "Active body",
        {"title": "Active plan", "tier": "epic", "status": "wip"},
        "Active body",
        None,
        (1, 2, 3, 4),
    )
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha", display_name="Alpha", workspace_dir=str(tmp_path)
            ),
        ),
    )
    monkeypatch.setattr(plans_data, "_load_proposals", lambda *_args: ())
    monkeypatch.setattr(
        plans_data, "_project_beads_dir", lambda _project: tmp_path / "beads"
    )
    monkeypatch.setattr(
        plans_data, "_project_document_roots", lambda _item: {"plans": tmp_path}
    )
    monkeypatch.setattr(plans_data, "_store_mtime_key", lambda *_args: ("mtime",))
    monkeypatch.setattr(plans_data, "_load_project_beads", lambda _path: [object()])
    monkeypatch.setattr(
        plans_data,
        "build_bead_plan_links",
        lambda *_args, **_kwargs: {("alpha", "alpha-1"): link},
    )
    monkeypatch.setattr(
        plans_data, "_load_linked_plan_document", lambda *_args, **_kwargs: document
    )
    monkeypatch.setattr(
        plans_data,
        "_load_project_archive",
        lambda _role, _root: (
            _match(active_path, "Active plan"),
            _match(archived_path, "Archived plan", status="done"),
        ),
    )

    snapshot = plans_data.load_plans_snapshot("alpha", force=True)

    assert [item.document.path for item in snapshot.active] == [str(active_path)]
    assert [item.match.plan.path for item in snapshot.archive] == [str(archived_path)]
    assert snapshot.bead_plan_links[("alpha", "alpha-1")] is link
    assert not hasattr(snapshot, "tasks")
    assert not hasattr(snapshot, "epics")
    assert not hasattr(snapshot, "phases_by_epic")


def test_snapshot_reuses_unchanged_previous_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha", display_name="Alpha", workspace_dir=str(tmp_path)
            ),
        ),
    )
    monkeypatch.setattr(plans_data, "_load_proposals", lambda *_args: ())
    monkeypatch.setattr(plans_data, "_project_beads_dir", lambda _project: None)
    monkeypatch.setattr(plans_data, "_project_document_roots", lambda _item: {})
    first = plans_data.load_plans_snapshot("alpha", force=True)

    assert plans_data.load_plans_snapshot("alpha", previous=first) is first
