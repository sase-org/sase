"""CLI coverage for sized phases and nested child epics."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
import json
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser


@pytest.fixture
def nested_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Issue]]:
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    plan_paths = {
        name: tmp_path / f"{name}.md"
        for name in ("root", "phase_child", "epic_child", "deep_child")
    }
    for path in plan_paths.values():
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    with BeadProject(tmp_path) as project:
        root = project.create(
            "Root Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=str(plan_paths["root"]),
        )
        phase = project.create("Root Phase", IssueType.PHASE, parent_id=root.id)
        phase = project.update(phase.id, size="medium")
        phase_child = project.create(
            "Phase Child Epic",
            IssueType.PLAN,
            parent_id=phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["phase_child"]),
        )
        nested_phase = project.create(
            "Nested Phase",
            IssueType.PHASE,
            parent_id=phase_child.id,
        )
        nested_phase = project.update(nested_phase.id, size="large")
        deep_child = project.create(
            "Deep Child Epic",
            IssueType.PLAN,
            parent_id=nested_phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["deep_child"]),
        )
        epic_child = project.create(
            "Epic Child Epic",
            IssueType.PLAN,
            parent_id=root.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["epic_child"]),
        )

    yield {
        "root": root,
        "phase": phase,
        "phase_child": phase_child,
        "nested_phase": nested_phase,
        "deep_child": deep_child,
        "epic_child": epic_child,
    }


def _show(issue: Issue, capsys: pytest.CaptureFixture[str]) -> str:
    bead_cli.handle_bead_show(argparse.Namespace(id=issue.id))
    return capsys.readouterr().out


def test_show_phase_displays_size_and_rootward_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(phase, capsys)

    assert "Size: medium" in out
    assert f"↑ {phase.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "From parent epic bead" in out


def test_show_plan_splits_phases_from_child_epics(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = nested_store["root"]
    phase = nested_store["phase"]
    epic_child = nested_store["epic_child"]

    out = _show(root, capsys)

    assert "CHILDREN\n  PHASES" in out
    assert f"○ {phase.id}: {phase.title}   [OPEN] · Size: medium" in out
    assert "  CHILD EPICS" in out
    assert f"○ {epic_child.id}: {epic_child.title}   [OPEN] · Tier: epic" in out
    assert nested_store["phase_child"].id not in out


def test_show_child_epic_under_phase_has_lineage_and_own_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["phase_child"]
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert f"↑ {child.id} ← phase {phase.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "phase_child.md" in out


def test_show_child_epic_under_epic_has_full_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["epic_child"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert f"↑ {child.id} ← epic {root.id}" in out
    assert "EPIC PLAN" in out
    assert "epic_child.md" in out


def test_show_deep_nested_child_epic_has_complete_lineage(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    child = nested_store["deep_child"]
    nested_phase = nested_store["nested_phase"]
    phase_child = nested_store["phase_child"]
    phase = nested_store["phase"]
    root = nested_store["root"]

    out = _show(child, capsys)

    assert (
        f"↑ {child.id} ← phase {nested_phase.id} ← epic {phase_child.id}"
        f" ← phase {phase.id} ← epic {root.id}"
    ) in out


def test_search_json_keeps_phase_size_in_machine_output(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]
    args = create_parser().parse_args(["bead", "search", "medium", "--format", "json"])

    bead_cli.handle_bead_search(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["results"][0]["issue"]["id"] == phase.id
    assert payload["results"][0]["issue"]["size"] == "medium"
    assert payload["results"][0]["matched_fields"] == ["size"]
