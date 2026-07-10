"""Tests for the provider-owned SDD init planner."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main.init_registry import iter_init_command_specs
from sase.main.sdd_handler import plan_sdd_init, run_sdd_init
from sase.sdd.store import SddStore


def _args(path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"path": str(path), "check": False}
    values.update(overrides)
    return argparse.Namespace(**values)


def _mark_project(path: Path) -> None:
    (path / ".git").mkdir()


def test_plan_providerless_project_targets_local_fallback_without_config_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: None)

    plan = plan_sdd_init(_args(tmp_path))

    assert plan.has_changes is True
    assert all(action.path.name != "sase.yml" for action in plan.actions)
    assert all(
        action.path.is_relative_to(tmp_path / ".sase" / "sdd")
        for action in plan.actions
    )
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_plan_github_reports_companion_and_legacy_import_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    legacy = tmp_path / "sdd" / "research" / "note.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("notes\n", encoding="utf-8")
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: "github")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda _name: "separate_repo",
    )

    plan = plan_sdd_init(_args(tmp_path))

    details = {action.detail for action in plan.actions}
    assert any("create or connect" in detail for detail in details)
    assert any("import legacy" in detail for detail in details)
    assert legacy.read_text() == "notes\n"
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_plan_non_project_reports_blocker(tmp_path: Path) -> None:
    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers
    assert "not a project directory" in plan.blockers[0]


def test_run_uses_materialized_path_and_does_not_write_project_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    sdd_dir = tmp_path / ".sase" / "sdd"
    store = SddStore("separate_repo", sdd_dir, sdd_dir, "github", "remote")
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda _path, _workspace_num: store,
    )

    assert run_sdd_init(_args(tmp_path)) == 0
    assert (sdd_dir / "README.md").is_file()
    assert not (tmp_path / "sase.yml").exists()


def test_init_registry_keeps_sdd_alias() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    assert specs["sdd"].plan is plan_sdd_init
    assert specs["sdd"].run is run_sdd_init
