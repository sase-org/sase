"""Unit tests for the ``sase bead show`` store router."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.bead import cross_project
from sase.bead.cli_show_batch import resolve_show_batch
from sase.bead.cli_show_router import ShowStoreRouter, ShowStoreRoutingError
from sase.bead.cross_project import BeadStoreOrigin
from sase.bead.model import Issue, IssueType


class _View:
    def __init__(self, issues: dict[str, Issue]) -> None:
        self.issues = issues
        self.seen: list[str] = []
        self.closed = False

    def __enter__(self) -> _View:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.closed = True

    def show(self, issue_id: str) -> Issue:
        self.seen.append(issue_id)
        if issue_id in self.issues:
            return self.issues[issue_id]
        raise KeyError(issue_id)

    def get_epic_children(self, _issue_id: str) -> list[Issue]:
        return []

    def list_issues(self) -> list[Issue]:
        return list(self.issues.values())


def test_resolve_show_batch_consults_local_view_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_issue = Issue(id="bob-cli-1", title="Local", issue_type=IssueType.TASK)
    local = _View({local_issue.id: local_issue})
    calls = 0

    def fail_if_called(_bead_id: str) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("cross-project routing should not run")

    monkeypatch.setattr(cross_project, "origin_for_bead_id", fail_if_called)

    batch = resolve_show_batch(
        local,
        ["bob-cli-1"],
        format_name="compact",
        include_links=False,
    )

    assert [entry.issue.title for entry in batch.entries] == ["Local"]
    assert local.seen == ["bob-cli-1"]
    assert calls == 0


def test_router_opens_each_foreign_store_once_and_closes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign_issue = Issue(id="bob-cli-1", title="Foreign", issue_type=IssueType.TASK)
    foreign = _View({foreign_issue.id: foreign_issue})
    local = _View({})
    beads_dir = tmp_path / "bob" / "sdd" / "beads"
    origin = BeadStoreOrigin(
        project_key="bob-cli",
        project_label="bob-cli",
        primary_workspace=tmp_path / "bob",
        beads_dir=beads_dir,
    )
    opened: list[Path] = []

    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)

    def fake_open(path: Path) -> _View:
        opened.append(path)
        return foreign

    monkeypatch.setattr(
        "sase.bead.cli_show_router.open_bead_project_for_beads_dir", fake_open
    )

    with ShowStoreRouter(local) as router:
        first = router.foreign_store_for_bead_id("bob-cli-1")
        second = router.foreign_store_for_bead_id("bob-cli-2")

    assert first is not None
    assert second is not None
    assert first.view is foreign
    assert second.view is foreign
    assert opened == [beads_dir]
    assert foreign.closed is True


def test_router_reports_unmaterialized_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = BeadStoreOrigin(
        project_key="bob-cli",
        project_label="bob-cli",
        primary_workspace=tmp_path / "bob",
        beads_dir=None,
    )
    monkeypatch.setattr(cross_project, "origin_for_bead_id", lambda _id: origin)

    with ShowStoreRouter(_View({})) as router:
        with pytest.raises(ShowStoreRoutingError) as excinfo:
            router.foreign_store_for_bead_id("bob-cli-1")

    assert "project 'bob-cli' owns 'bob-cli-1'" in str(excinfo.value)
    assert "not materialized" in str(excinfo.value)
