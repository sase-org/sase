"""Compatibility wrappers delegate primary bead paths to Rust facades."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.workspace import MergedBeadView
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
        assert project.beads_dir in calls[0]["workspace_beads_dirs"]


def test_merged_bead_view_delegates_to_rust_merged_read(
    tmp_path: Path, monkeypatch
) -> None:
    beads_dirs = [tmp_path / "one" / ".sase_beads", tmp_path / "two" / ".sase_beads"]
    expected = [Issue(id="ready-1", title="Ready", status=Status.OPEN)]
    calls: list[list[Path]] = []

    def fake_merged_ready(paths: list[Path]) -> list[Issue]:
        calls.append(paths)
        return expected

    monkeypatch.setattr(bead_read_facade, "merged_ready", fake_merged_ready)

    with MergedBeadView(beads_dirs) as view:
        assert view.ready() == expected
    assert calls == [beads_dirs]
