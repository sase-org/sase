"""Tests for canonical bead-store status lookups."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead.store_locator import (
    bead_statuses_for_project,
    open_bead_candidates_for_project,
)


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


def test_bead_statuses_for_project_uses_one_list_query_instead_of_show_n_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        first = project.create("First", IssueType.PLAN)
        second = project.create("Second", IssueType.PLAN)
        project.update(second.id, status="in_progress")

    beads_dir = tmp_path / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [beads_dir] if project == "known" else [],
    )
    show_calls: list[str] = []
    list_calls: list[object] = []
    original_show = BeadProject.show
    original_list = BeadProject.list_issues

    def counting_show(self: BeadProject, issue_id: str) -> object:
        show_calls.append(issue_id)
        return original_show(self, issue_id)

    def counting_list(self: BeadProject, **kwargs: object) -> object:
        list_calls.append(kwargs)
        return original_list(self, **kwargs)

    monkeypatch.setattr(BeadProject, "show", counting_show)
    monkeypatch.setattr(BeadProject, "list_issues", counting_list)

    assert bead_statuses_for_project("known", [first.id, second.id, "missing"]) == {
        first.id: "open",
        second.id: "in_progress",
    }
    assert show_calls == []
    assert len(list_calls) == 1


def test_bead_statuses_for_project_resolves_unique_id_suffixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        issue = project.create("Claimed", IssueType.PLAN)
        project.update(issue.id, status="claimed")

    beads_dir = tmp_path / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [beads_dir] if project == "known" else [],
    )
    suffix = issue.id.rsplit("-", 1)[-1]
    assert suffix != issue.id
    assert bead_statuses_for_project("known", [suffix]) == {suffix: "claimed"}


def test_bead_statuses_for_project_returns_empty_mapping_for_no_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        project.create("Open", IssueType.PLAN)

    beads_dir = tmp_path / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [beads_dir] if project == "known" else [],
    )
    list_calls: list[object] = []
    original_list = BeadProject.list_issues

    def counting_list(self: BeadProject, **kwargs: object) -> object:
        list_calls.append(kwargs)
        return original_list(self, **kwargs)

    monkeypatch.setattr(BeadProject, "list_issues", counting_list)
    assert bead_statuses_for_project("known", []) == {}
    assert list_calls == []


def test_open_bead_candidates_for_project_excludes_closed_beads(
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

    candidates = open_bead_candidates_for_project("known")
    assert candidates is not None
    candidate_ids = {issue.id for issue in candidates}
    assert claimed.id in candidate_ids
    assert closed.id not in candidate_ids


def test_open_bead_candidates_for_project_returns_none_for_unknown_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [],
    )
    assert open_bead_candidates_for_project("unknown") is None
