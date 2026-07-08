"""Tests for the SDD ``sase init`` planner."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main.init_registry import iter_init_command_specs
from sase.main.sdd_handler import plan_sdd_init, run_sdd_init
from sase.sdd.files import (
    expected_sdd_directory_map,
    expected_sdd_directory_readmes,
    expected_sdd_readme,
    write_sdd_readme,
)


def _args(path: Path) -> argparse.Namespace:
    return argparse.Namespace(path=str(path))


def _write_enabled_config(path: Path) -> None:
    (path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )


def _mark_project(path: Path) -> None:
    (path / ".git").mkdir()


def _rel_actions(path: Path) -> set[tuple[str, Path]]:
    plan = plan_sdd_init(_args(path))
    sdd_root = path / "sdd"
    return {
        (action.operation, action.path.relative_to(sdd_root))
        for action in plan.actions
        if action.path.is_relative_to(sdd_root)
    }


def test_sdd_plan_missing_tree_reports_create_actions_without_writing(
    tmp_path: Path,
) -> None:
    _mark_project(tmp_path)

    plan = plan_sdd_init(_args(tmp_path))

    assert not (tmp_path / "sdd").exists()
    assert not (tmp_path / "sase.yml").exists()
    assert {action.operation for action in plan.actions} == {"create"}
    assert len(plan.actions) == len(expected_sdd_directory_readmes(str(tmp_path))) + 3
    assert tmp_path / "sase.yml" in {action.path for action in plan.actions}
    assert expected_sdd_readme(str(tmp_path)).path in {
        action.path for action in plan.actions
    }
    assert expected_sdd_directory_map(str(tmp_path)).path in {
        action.path for action in plan.actions
    }
    assert plan.has_changes is True


def test_sdd_plan_non_project_reports_blocker_without_writing(
    tmp_path: Path,
) -> None:
    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers == (
        "sase init sdd: not a project directory (no VCS found); "
        "skipping SDD initialization",
    )
    assert not (tmp_path / "sdd").exists()
    assert not (tmp_path / "sase.yml").exists()


def test_sdd_run_non_project_skips_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_sdd_init(_args(tmp_path)) == 1

    captured = capsys.readouterr()
    assert "not a project directory" in captured.err
    assert not (tmp_path / "sdd").exists()
    assert not (tmp_path / "sase.yml").exists()


def test_sdd_run_invokes_materialization_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    calls: list[tuple[Path, int]] = []

    def fake_materialize(path: Path, workspace_num: int) -> None:
        calls.append((path, workspace_num))

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", fake_materialize)

    assert run_sdd_init(_args(tmp_path)) == 0
    assert calls == [(tmp_path, 1)]
    assert (tmp_path / "sase.yml").exists()


def test_sdd_plan_stale_readmes_report_update_actions(tmp_path: Path) -> None:
    _mark_project(tmp_path)
    write_sdd_readme(str(tmp_path))
    _write_enabled_config(tmp_path)
    top_readme = expected_sdd_readme(str(tmp_path)).path
    tales_readme = next(
        file
        for file in expected_sdd_directory_readmes(str(tmp_path))
        if file.path.parent.name == "tales"
    ).path
    top_readme.write_text("stale top-level README\n", encoding="utf-8")
    tales_readme.write_text("stale directory README\n", encoding="utf-8")

    assert _rel_actions(tmp_path) == {
        ("update", Path("README.md")),
        ("update", Path("tales/README.md")),
    }


def test_sdd_plan_corrupt_directory_map_reports_update_action(tmp_path: Path) -> None:
    _mark_project(tmp_path)
    write_sdd_readme(str(tmp_path))
    _write_enabled_config(tmp_path)
    directory_map = expected_sdd_directory_map(str(tmp_path)).path
    directory_map.write_bytes(b"not a png\n")

    assert _rel_actions(tmp_path) == {
        ("update", Path("assets/sdd-directory-map.png")),
    }


def test_sdd_plan_identical_outputs_is_empty(tmp_path: Path) -> None:
    _mark_project(tmp_path)
    write_sdd_readme(str(tmp_path))
    _write_enabled_config(tmp_path)

    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.has_changes is False
    assert "current" in plan.summary


def test_sdd_plan_current_outputs_without_config_reports_config_action(
    tmp_path: Path,
) -> None:
    _mark_project(tmp_path)
    write_sdd_readme(str(tmp_path))

    plan = plan_sdd_init(_args(tmp_path))

    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.path == tmp_path / "sase.yml"
    assert action.operation == "create"
    assert "legacy SDD init config" in plan.summary


def test_sdd_plan_existing_enabled_config_reports_no_config_action(
    tmp_path: Path,
) -> None:
    _mark_project(tmp_path)
    _write_enabled_config(tmp_path)

    plan = plan_sdd_init(_args(tmp_path))

    assert tmp_path / "sase.yml" not in {action.path for action in plan.actions}


def test_sdd_init_registry_includes_sdd_planner() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}

    assert "sdd" in specs
    assert specs["sdd"].plan is plan_sdd_init
