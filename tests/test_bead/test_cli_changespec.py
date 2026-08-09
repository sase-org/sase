"""CLI coverage for Patch metadata on bead plan creation."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import PhaseSize
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    yield tmp_path


def _create_args(
    *,
    title: str,
    type_value: str,
    tier: str | None = None,
    patch: str | None = None,
    bug_id: str | None = None,
    model: str | None = None,
    size: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        title=title,
        type=type_value,
        description=None,
        assignee=None,
        tier=tier,
        patch=patch,
        bug_id=bug_id,
        model=model,
        size=size,
    )


def test_create_plan_accepts_patch_and_bug(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    args = _create_args(
        title="Epic",
        type_value=f"plan({plan})",
        patch="feature_epic",
        bug_id="12345",
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as proj:
        issue = proj.list_issues()[0]
        assert issue.design == "plan.md"
        assert issue.changespec_name == "feature_epic"
        assert issue.changespec_bug_id == "12345"
    assert "Created plan" in capsys.readouterr().out


def test_create_plan_accepts_patch_alias(
    project_dir: Path,
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    parser = create_parser()
    args = parser.parse_args(
        [
            "bead",
            "create",
            "-T",
            f"plan({plan})",
            "-t",
            "Epic",
            "--patch",
            "feature_epic",
        ]
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as proj:
        issue = proj.list_issues()[0]
        assert issue.patch_name == "feature_epic"


def test_create_plan_stores_sibling_workspace_plan_path_relative_to_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_101"
    plan = sibling / "sdd" / "plans" / "202605" / "roadmap.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Roadmap\n")
    with BeadProject.init(primary):
        pass
    isolate_bead_store_resolution(
        monkeypatch,
        sibling,
        primary=primary,
        workspace_num=101,
    )
    args = _create_args(title="Epic", type_value=f"plan({plan})", tier="epic")

    bead_cli.handle_bead_create(args)

    with BeadProject(primary) as proj:
        issue = proj.list_issues()[0]
        assert issue.design == "plans:202605/roadmap.md"
    assert "Created plan" in capsys.readouterr().out


def test_create_plan_preserves_external_absolute_plan_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    external = tmp_path / "external" / "roadmap.md"
    external.parent.mkdir()
    external.write_text("# Roadmap\n")
    with BeadProject.init(primary):
        pass
    isolate_bead_store_resolution(monkeypatch, primary)
    args = _create_args(title="Epic", type_value=f"plan({external})", tier="epic")

    bead_cli.handle_bead_create(args)

    with BeadProject(primary) as proj:
        issue = proj.list_issues()[0]
        assert issue.design == str(external.resolve())
    assert "Created plan" in capsys.readouterr().out


def test_show_displays_patch_metadata(
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

    args = create_parser().parse_args(["bead", "show", epic.id])
    bead_cli.handle_bead_show(args)

    out = capsys.readouterr().out
    assert "PATCH" in out
    assert "Name: feature_epic" in out
    assert "Bug ID: 12345" in out


def test_show_phase_omits_parent_plan_when_parent_has_no_design(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create(
            "Epic",
            issue_type=bead_cli.IssueType.PLAN,
            tier="epic",
        )
        phase = proj.create(
            "Phase",
            issue_type=bead_cli.IssueType.PHASE,
            parent_id=epic.id,
        )

    args = create_parser().parse_args(["bead", "show", phase.id])
    bead_cli.handle_bead_show(args)

    out = capsys.readouterr().out
    assert "\nPARENT\n" in out
    assert "\nEPIC PLAN\n" not in out
    assert "\nPARENT PLAN\n" not in out
    assert "From parent" not in out


def test_create_phase_rejects_patch_metadata(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    args = _create_args(
        title="Phase",
        type_value=f"phase({epic.id})",
        patch="feature_epic",
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(args)

    assert excinfo.value.code == 1
    assert "only be attached to plan beads" in capsys.readouterr().err


def test_create_rejects_bug_id_without_patch(
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
    assert "--bug-id requires --patch/--changespec" in capsys.readouterr().err


def test_parser_accepts_model_on_create_short_and_long() -> None:
    parser = create_parser()
    short = parser.parse_args(
        ["bead", "create", "-t", "x", "-T", "phase(p)", "-m", "claude/opus"]
    )
    long = parser.parse_args(
        ["bead", "create", "-t", "x", "-T", "phase(p)", "--model", "codex/gpt-5.5"]
    )
    assert short.model == "claude/opus"
    assert long.model == "codex/gpt-5.5"


def test_parser_accepts_model_on_update_short_and_long() -> None:
    parser = create_parser()
    short = parser.parse_args(["bead", "update", "x", "-m", "claude/opus"])
    long_clear = parser.parse_args(["bead", "update", "x", "--model", ""])
    assert short.model == "claude/opus"
    assert long_clear.model == ""


def test_parser_accepts_size_on_create_and_update_short_and_long() -> None:
    parser = create_parser()
    create_short = parser.parse_args(
        ["bead", "create", "-t", "x", "-T", "phase(p)", "-z", "xsmall"]
    )
    create_long = parser.parse_args(
        [
            "bead",
            "create",
            "-t",
            "x",
            "-T",
            "phase(p)",
            "--size",
            "small",
        ]
    )
    update_short = parser.parse_args(["bead", "update", "x", "-z", "large"])
    update_long = parser.parse_args(["bead", "update", "x", "--size", "xlarge"])
    assert create_short.size == "xsmall"
    assert create_long.size == "small"
    assert update_short.size == "large"
    assert update_long.size == "xlarge"


def test_create_and_update_phase_size_persist(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    bead_cli.handle_bead_create(
        _create_args(
            title="Sized phase",
            type_value=f"phase({epic.id})",
            size="xsmall",
        )
    )
    with BeadProject(project_dir) as proj:
        phase = proj.get_epic_children(epic.id)[0]
        assert phase.size is PhaseSize.XSMALL

    bead_cli.handle_bead_update(
        argparse.Namespace(
            ids=[phase.id],
            status=None,
            title=None,
            description=None,
            notes=None,
            design=None,
            assignee=None,
            tier=None,
            model=None,
            size="xlarge",
        )
    )

    with BeadProject(project_dir) as proj:
        assert proj.show(phase.id).size is PhaseSize.XLARGE
    capsys.readouterr()


def test_create_rejects_size_for_plan_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_create(
            _create_args(
                title="Invalid sized epic",
                type_value=f"plan({plan})",
                size="large",
            )
        )

    assert excinfo.value.code == 1
    assert "--size can only be set on phase or task beads" in capsys.readouterr().err


def test_update_rejects_size_for_plan_bead(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_update(
            argparse.Namespace(
                ids=[epic.id],
                status=None,
                title=None,
                description=None,
                notes=None,
                design=None,
                assignee=None,
                tier=None,
                model=None,
                size="large",
            )
        )

    assert excinfo.value.code == 1
    assert "phase" in capsys.readouterr().err.lower()


def test_create_with_model_persists(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = project_dir / "plan.md"
    plan.write_text("# Plan\n")
    args = _create_args(
        title="Epic",
        type_value=f"plan({plan})",
        model="claude/opus",
    )

    bead_cli.handle_bead_create(args)

    with BeadProject(project_dir) as proj:
        issue = proj.list_issues()[0]
        assert issue.model == "claude/opus"
    capsys.readouterr()


def test_update_clears_model_with_empty_string(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create(
            "Epic",
            issue_type=bead_cli.IssueType.PLAN,
            model="codex/gpt-5.5",
        )

    bead_cli.handle_bead_update(
        argparse.Namespace(
            ids=[epic.id],
            status=None,
            title=None,
            description=None,
            notes=None,
            design=None,
            assignee=None,
            tier=None,
            model="",
        )
    )

    with BeadProject(project_dir) as proj:
        assert proj.show(epic.id).model == ""
    capsys.readouterr()


def test_update_changes_model_value(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    bead_cli.handle_bead_update(
        argparse.Namespace(
            ids=[epic.id],
            status=None,
            title=None,
            description=None,
            notes=None,
            design=None,
            assignee=None,
            tier=None,
            model="codex/gpt-5.5",
        )
    )

    with BeadProject(project_dir) as proj:
        assert proj.show(epic.id).model == "codex/gpt-5.5"
    capsys.readouterr()


def test_show_displays_model(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create(
            "Epic", issue_type=bead_cli.IssueType.PLAN, model="claude/opus"
        )

    args = create_parser().parse_args(["bead", "show", epic.id])
    bead_cli.handle_bead_show(args)

    assert "Model: claude/opus" in capsys.readouterr().out


def test_show_omits_model_when_empty(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        epic = proj.create("Epic", issue_type=bead_cli.IssueType.PLAN)

    args = create_parser().parse_args(["bead", "show", epic.id])
    bead_cli.handle_bead_show(args)

    assert "Model:" not in capsys.readouterr().out
