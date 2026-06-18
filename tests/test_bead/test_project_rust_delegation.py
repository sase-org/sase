"""Compatibility wrappers delegate primary bead paths to Rust facades."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import BeadSearchMatch, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.core import bead_mutation_facade, bead_read_facade


def test_bead_project_show_delegates_to_rust_read(tmp_path: Path, monkeypatch) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(id="delegated-1", title="Delegated", issue_type=IssueType.PLAN)
        calls: list[tuple[Path | str, str]] = []

        def fake_show(beads_dir: Path | str, issue_id: str) -> Issue:
            calls.append((beads_dir, issue_id))
            return expected

        monkeypatch.setattr(bead_read_facade, "show", fake_show)

        assert project.show("delegated-1") is expected
        assert calls == [(project.beads_dir, "delegated-1")]


def test_bead_project_create_delegates_to_rust_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(id="delegated-1", title="Delegated", issue_type=IssueType.PLAN)
        calls: list[dict[str, Any]] = []

        def fake_create(
            beads_dir: Path | str, **kwargs: Any
        ) -> tuple[Issue, dict[str, Any]]:
            calls.append({"beads_dir": beads_dir, **kwargs})
            return expected, {"operation": "create"}

        monkeypatch.setattr(bead_mutation_facade, "create", fake_create)
        monkeypatch.setattr(project, "_refresh_db_from_jsonl", lambda: None)

        assert project.create("Delegated", IssueType.PLAN) is expected
        assert calls[0]["beads_dir"] == project.beads_dir
        assert calls[0]["title"] == "Delegated"
        assert calls[0]["issue_type"] == IssueType.PLAN
        assert "workspace_beads_dirs" not in calls[0]


def test_bead_project_show_returns_issue_with_model(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = Issue(
            id="delegated-1",
            title="Delegated",
            issue_type=IssueType.PLAN,
            model="codex/gpt-5.5",
        )

        calls: list[tuple[Path | str, str]] = []

        def fake_show(beads_dir: Path | str, issue_id: str) -> Issue:
            calls.append((beads_dir, issue_id))
            return expected

        monkeypatch.setattr(bead_read_facade, "show", fake_show)

        result = project.show("delegated-1")
        assert result is not None
        assert result.model == "codex/gpt-5.5"
        assert calls == [(project.beads_dir, "delegated-1")]


def test_bead_project_search_delegates_to_rust_read(
    tmp_path: Path, monkeypatch
) -> None:
    with BeadProject.init(tmp_path) as project:
        expected = [
            BeadSearchMatch(
                issue=Issue(
                    id="delegated-1",
                    title="Delegated",
                    issue_type=IssueType.PLAN,
                ),
                matched_fields=["title"],
            )
        ]
        calls: list[dict[str, Any]] = []

        def fake_search(
            beads_dir: Path | str, query: str, **kwargs: Any
        ) -> list[BeadSearchMatch]:
            calls.append({"beads_dir": beads_dir, "query": query, **kwargs})
            return expected

        monkeypatch.setattr(bead_read_facade, "search", fake_search)

        assert project.search("delegated", statuses=[Status.OPEN], limit=1) is expected
        assert calls == [
            {
                "beads_dir": project.beads_dir,
                "query": "delegated",
                "statuses": [Status.OPEN],
                "issue_types": None,
                "tiers": None,
                "limit": 1,
            }
        ]
