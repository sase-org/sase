"""Multi-project data-layer coverage for the Artifacts Plans pane."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.artifacts import plans_data
from sase.ace.tui.widgets.artifacts.plans_data import load_plans_snapshot
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.project import BeadProject
from sase.plan_search.model import Plan, PlanSearchMatch


def _archive(root: Path, *, title: str, created_at: str) -> PlanSearchMatch:
    path = root / "202607" / f"{title.casefold()}.md"
    return PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(path),
            relpath=f"202607/{path.name}",
            name=path.stem,
            title=title,
            status="wip",
            created_at=created_at,
            prompt_link="",
            summary="",
            body=f"# {title}",
        ),
        matched_fields=[],
        score=1.0,
    )


def _project(
    name: str,
    *,
    workspace_dir: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        project=name,
        display_name=name.title(),
        workspace_dir=workspace_dir,
    )


def test_all_projects_snapshot_attributes_each_entry_and_merges_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {name: tmp_path / name for name in ("alpha", "beta")}
    epics: dict[str, Issue] = {}
    phases: dict[str, Issue] = {}
    for name, root in roots.items():
        with BeadProject.init(root, beads_dirname="beads") as project:
            epics[name] = project.create(
                f"{name.title()} epic",
                IssueType.PLAN,
                tier=BeadTier.EPIC,
            )
            phases[name] = project.create(
                f"{name.title()} phase",
                IssueType.PHASE,
                parent_id=epics[name].id,
            )

    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _scope: tuple(
            _project(name, workspace_dir=str(root / "workspace"))
            for name, root in roots.items()
        ),
    )
    monkeypatch.setattr(
        plans_data,
        "_project_beads_dir",
        lambda project: roots[project] / "beads",
    )
    monkeypatch.setattr(
        plans_data,
        "_load_proposals",
        lambda _scope, _enabled: (),
    )
    monkeypatch.setattr(
        plans_data,
        "_load_project_archive",
        lambda root: (
            _archive(
                root,
                title=root.name.title(),
                created_at=(
                    "2026-07-16 12:00:00"
                    if root.name == "beta"
                    else "2026-07-15 12:00:00"
                ),
            ),
        ),
    )

    snapshot = load_plans_snapshot(None, force=True)

    assert snapshot.projects == ("alpha", "beta")
    assert {(entry.project, entry.issue.id) for entry in snapshot.epics} == {
        (name, epic.id) for name, epic in epics.items()
    }
    assert {
        (project, entry.issue.id)
        for (project, _epic_id), entries in snapshot.phases_by_epic.items()
        for entry in entries
    } == {(name, phase.id) for name, phase in phases.items()}
    assert [entry.project for entry in snapshot.archive] == ["beta", "alpha"]
    assert snapshot.workspace_dirs == {
        name: str(root / "workspace") for name, root in roots.items()
    }


def test_all_projects_snapshot_isolates_one_project_store_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = {name: tmp_path / name for name in ("alpha", "beta")}
    alpha_epic = Issue(
        id="shared-1",
        title="Alpha epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _scope: tuple(_project(name) for name in roots),
    )
    monkeypatch.setattr(
        plans_data,
        "_project_beads_dir",
        lambda project: roots[project] / "beads",
    )
    monkeypatch.setattr(
        plans_data,
        "_load_proposals",
        lambda _scope, _enabled: (),
    )

    def load_beads(beads_dir: Path):
        if beads_dir.parent.name == "beta":
            raise OSError("corrupt beta store")
        return [alpha_epic], frozenset({alpha_epic.id}), frozenset()

    monkeypatch.setattr(plans_data, "_load_project_beads", load_beads)
    monkeypatch.setattr(plans_data, "_load_project_archive", lambda _root: ())

    snapshot = load_plans_snapshot(None, force=True)

    assert [(entry.project, entry.issue.id) for entry in snapshot.epics] == [
        ("alpha", alpha_epic.id)
    ]
    assert "corrupt beta store" in snapshot.errors["beta"]
    assert "alpha" not in snapshot.errors


def test_source_key_reuses_cache_and_invalidates_when_enabled_set_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled = [_project("alpha")]
    load_calls: list[str] = []
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _scope: tuple(enabled),
    )
    monkeypatch.setattr(
        plans_data,
        "_project_beads_dir",
        lambda project: tmp_path / project / "beads",
    )
    monkeypatch.setattr(
        plans_data,
        "_load_proposals",
        lambda _scope, _enabled: (),
    )

    def load_beads(beads_dir: Path):
        load_calls.append(beads_dir.parent.name)
        return [], frozenset(), frozenset()

    monkeypatch.setattr(plans_data, "_load_project_beads", load_beads)
    monkeypatch.setattr(plans_data, "_load_project_archive", lambda _root: ())

    first = load_plans_snapshot(None, force=True)
    unchanged = load_plans_snapshot(None, previous=first)
    enabled.append(_project("beta"))
    changed = load_plans_snapshot(None, previous=unchanged)

    assert unchanged is first
    assert load_calls == ["alpha", "alpha", "beta"]
    assert changed is not first
    assert changed.projects == ("alpha", "beta")
    assert changed.source_key != first.source_key


def test_all_projects_archive_is_capped_after_recent_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = ("alpha", "beta", "gamma")
    monkeypatch.setattr(
        plans_data,
        "_resolve_projects",
        lambda _scope: tuple(_project(name) for name in projects),
    )
    monkeypatch.setattr(
        plans_data,
        "_project_beads_dir",
        lambda project: tmp_path / project / "beads",
    )
    monkeypatch.setattr(
        plans_data,
        "_load_proposals",
        lambda _scope, _enabled: (),
    )
    monkeypatch.setattr(
        plans_data,
        "_load_project_beads",
        lambda _root: ([], frozenset(), frozenset()),
    )

    def load_archive(root: Path) -> tuple[PlanSearchMatch, ...]:
        day = {"alpha": 14, "beta": 15, "gamma": 16}[root.name]
        return tuple(
            _archive(
                root,
                title=f"{root.name}-{index:02d}",
                created_at=f"2026-07-{day:02d} 12:00:{index:02d}",
            )
            for index in range(50)
        )

    monkeypatch.setattr(plans_data, "_load_project_archive", load_archive)

    snapshot = load_plans_snapshot(None, force=True)

    assert len(snapshot.archive) == 100
    assert snapshot.archive_truncated is True
    assert {entry.project for entry in snapshot.archive} == {"beta", "gamma"}
