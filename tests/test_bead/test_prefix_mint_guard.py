"""Regression coverage for automatic issue-prefix repair before minting."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.bead import cli_admin, cli_crud
from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.config import load_config, save_config
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update

KEY_PREFIX = "gh_bobs-org__bob-cli"
PROJECT_NAME = "bob-cli"


def test_top_level_create_repairs_key_prefix_before_minting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_ids = _seed_key_prefixed_top_level_beads(tmp_path)
    _stub_bob_cli_project(monkeypatch)

    with BeadProject(tmp_path) as project:
        issue = project.create("New top-level", IssueType.PLAN)
        assert issue.id == "bob-cli-6"
        assert project.last_prefix_repair == (KEY_PREFIX, PROJECT_NAME)
        assert {bead.id for bead in project.list_issues()} >= {
            *existing_ids,
            issue.id,
        }

    config = load_config(tmp_path / "sdd/beads")
    assert config["issue_prefix"] == PROJECT_NAME
    assert config["next_counter"] == 7
    assert config["owner"] == "owner@example.com"


def test_child_create_does_not_repair_key_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_id = _seed_key_prefixed_top_level_beads(tmp_path, count=1)[0]
    beads_dir = tmp_path / "sdd/beads"
    before = (beads_dir / "config.json").read_bytes()
    _stub_bob_cli_project(monkeypatch)

    with BeadProject(tmp_path) as project:
        child = project.create("Child", IssueType.PHASE, parent_id=parent_id)
        assert child.id == f"{parent_id}.1"
        assert project.last_prefix_repair is None

    assert (beads_dir / "config.json").read_bytes() == before


def test_custom_prefix_create_is_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with BeadProject.init(tmp_path):
        pass
    beads_dir = tmp_path / "sdd/beads"
    save_config(
        beads_dir,
        {"issue_prefix": "beads", "next_counter": 3, "owner": "owner@example.com"},
    )
    _stub_bob_cli_project(monkeypatch)

    with BeadProject(tmp_path) as project:
        issue = project.create("Custom prefix", IssueType.PLAN)
        assert issue.id == "beads-3"
        assert project.last_prefix_repair is None

    assert load_config(beads_dir)["issue_prefix"] == "beads"


def test_doctor_prefix_warning_disappears_after_auto_repair(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_key_prefixed_top_level_beads(project_dir, count=1)
    _stub_bob_cli_project(monkeypatch)

    with BeadProject(project_dir) as project:
        project.create("Repairing bead", IssueType.PLAN)

    cli_admin.handle_bead_doctor(_doctor_args())

    assert "is a ProjectSpec key" not in capsys.readouterr().out


def test_bead_create_reports_auto_prefix_repair(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_key_prefixed_top_level_beads(project_dir)
    _stub_bob_cli_project(monkeypatch)
    plan = project_dir / "design.md"
    plan.write_text("# Design\n", encoding="utf-8")

    cli_crud.handle_bead_create(
        argparse.Namespace(
            type=f"plan({plan})",
            changespec=None,  # legacy context field
            bug_id=None,
            tier=None,
            title="Created",
            description=None,
            assignee=None,
            model=None,
            size=None,
            ref=None,
        )
    )

    output = capsys.readouterr().out
    assert f"Issue prefix    {KEY_PREFIX} → {PROJECT_NAME}" in output
    assert "Created plan: bob-cli-6" in output


def test_plan_file_work_repairs_prefix_and_reports_it(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_key_prefixed_top_level_beads(project_dir)
    _stub_bob_cli_project(monkeypatch)
    source = project_dir / "incoming" / "rollout.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=True,
    )

    assert result.epic_id == "bob-cli-6"
    assert result.phase_bead_ids == ("bob-cli-6.1", "bob-cli-6.2", "bob-cli-6.3")
    output = capsys.readouterr().out
    assert f"Issue prefix    {KEY_PREFIX} → {PROJECT_NAME}" in output
    assert "Epic bead       bob-cli-6" in output


def _seed_key_prefixed_top_level_beads(
    root: Path, *, count: int = 5
) -> tuple[str, ...]:
    with BeadProject.init(root):
        pass
    beads_dir = root / "sdd/beads"
    save_config(
        beads_dir,
        {
            "issue_prefix": KEY_PREFIX,
            "next_counter": 1,
            "owner": "owner@example.com",
        },
    )
    ids: list[str] = []
    with BeadProject(root) as project:
        for index in range(1, count + 1):
            ids.append(
                project.create(
                    f"Existing {index}",
                    IssueType.PLAN,
                    tier=BeadTier.EPIC,
                ).id
            )
    assert ids == [f"{KEY_PREFIX}-{index}" for index in range(1, count + 1)]
    assert load_config(beads_dir)["next_counter"] == count + 1
    return tuple(ids)


def _stub_bob_cli_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: KEY_PREFIX,
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: PROJECT_NAME,
    )


def _doctor_args(**overrides: bool) -> argparse.Namespace:
    defaults = {
        "fix_design_refs": False,
        "fix_issue_prefix": False,
        "fix_projection": False,
        "yes": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
