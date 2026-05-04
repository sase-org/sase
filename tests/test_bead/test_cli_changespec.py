"""CLI coverage for ChangeSpec metadata on bead plan creation."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.project import BeadProject


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    yield tmp_path


def _create_args(
    *,
    title: str,
    type_value: str,
    tier: str | None = None,
    changespec: str | None = None,
    bug_id: str | None = None,
    epic_count: int | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        title=title,
        type=type_value,
        description=None,
        assignee=None,
        tier=tier,
        changespec=changespec,
        bug_id=bug_id,
        epic_count=epic_count,
    )


def test_create_plan_accepts_changespec_and_bug(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    args = _create_args(
        title="Epic",
        type_value=f"plan({plan})",
        changespec="feature_epic",
        bug_id="12345",
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as proj:
        issue = proj.list_issues()[0]
        assert issue.changespec_name == "feature_epic"
        assert issue.changespec_bug_id == "12345"
    assert "Created plan" in capsys.readouterr().out


def test_show_displays_changespec_metadata(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create(
            "Epic",
            issue_type=bead_cli.IssueType.PLAN,
            changespec_name="feature_epic",
            changespec_bug_id="12345",
        )

    bead_cli.handle_bead_show(argparse.Namespace(id=epic.id))

    out = capsys.readouterr().out
    assert "CHANGESPEC" in out
    assert "Name: feature_epic" in out
    assert "Bug ID: 12345" in out


def test_create_phase_rejects_changespec_metadata(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    args = _create_args(
        title="Phase",
        type_value=f"phase({epic.id})",
        changespec="feature_epic",
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(args)

    assert excinfo.value.code == 1
    assert "only be attached to plan beads" in capsys.readouterr().err


def test_create_rejects_bug_id_without_changespec(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    args = _create_args(
        title="Epic",
        type_value=f"plan({plan})",
        bug_id="12345",
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(args)

    assert excinfo.value.code == 1
    assert "--bug-id requires --changespec" in capsys.readouterr().err


def test_create_legend_accepts_epic_count(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "legend.md"
    plan.write_text("# Legend\n")
    args = _create_args(
        title="Legend",
        type_value=f"plan({plan})",
        tier="legend",
        epic_count=5,
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as proj:
        issue = proj.list_issues()[0]
        assert issue.epic_count == 5
    assert "Created plan" in capsys.readouterr().out


def test_show_displays_epic_count(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        legend = proj.create(
            "Legend",
            issue_type=bead_cli.IssueType.PLAN,
            tier="legend",
            epic_count=3,
        )

    bead_cli.handle_bead_show(argparse.Namespace(id=legend.id))

    assert "Epic Count: 3" in capsys.readouterr().out


def test_update_legend_epic_count(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        legend = proj.create(
            "Legend",
            issue_type=bead_cli.IssueType.PLAN,
            tier="legend",
            epic_count=3,
        )

    bead_cli.handle_bead_update(
        argparse.Namespace(
            id=legend.id,
            status=None,
            title=None,
            description=None,
            notes=None,
            design=None,
            assignee=None,
            tier=None,
            epic_count=6,
        )
    )

    with BeadProject(project_dir) as proj:
        assert proj.show(legend.id).epic_count == 6
    assert "Updated issue" in capsys.readouterr().out


def test_create_phase_rejects_epic_count(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    args = _create_args(
        title="Phase",
        type_value=f"phase({epic.id})",
        epic_count=2,
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(args)

    assert excinfo.value.code == 1
    assert "only be set on plan beads" in capsys.readouterr().err


def test_create_epic_rejects_epic_count(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    args = _create_args(
        title="Epic",
        type_value=f"plan({plan})",
        tier="epic",
        epic_count=2,
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(args)

    assert excinfo.value.code == 1
    assert "only be set on legend plan beads" in capsys.readouterr().err
