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


def _mark_project(path: Path, *, managed: bool = True) -> None:
    (path / ".git").mkdir()
    if managed:
        (path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")


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
    assert all(
        isinstance(action.new_content, bytes)
        if action.path.suffix == ".png"
        else isinstance(action.new_content, str)
        for action in plan.actions
    )
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_plan_github_reports_both_split_sidecars_without_writing(
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
    assert any("plans sidecar repository" in detail for detail in details)
    assert any("research sidecar repository" in detail for detail in details)
    assert any("plans sidecar README.md" in detail for detail in details)
    assert any("research sidecar README.md" in detail for detail in details)
    assert legacy.read_text() == "notes\n"
    assert not (tmp_path / ".sase" / "sdd").exists()


def test_plan_non_project_reports_blocker(tmp_path: Path) -> None:
    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers
    assert "not a project directory" in plan.blockers[0]


@pytest.mark.parametrize(
    "config_text",
    [
        None,
        "is_sase_managed: false\n",
        "memory:\n  enabled: true\n",
    ],
)
def test_unmanaged_plan_skips_before_provider_or_generated_file_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str | None,
) -> None:
    _mark_project(tmp_path, managed=False)
    if config_text is not None:
        (tmp_path / "sase.yml").write_text(config_text, encoding="utf-8")
    provider_calls: list[Path] = []
    generated_calls: list[str] = []
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda root: provider_calls.append(root) or "local",
    )
    monkeypatch.setattr(
        "sase.sdd.files.plan_sdd_init_actions",
        lambda path: generated_calls.append(path) or (),
    )

    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.blockers == ()
    assert "not SASE-managed" in plan.summary
    assert provider_calls == []
    assert generated_calls == []
    assert not (tmp_path / ".sase").exists()


@pytest.mark.parametrize(
    "config_text, expected_error",
    [
        ('is_sase_managed: "yes"\n', "must be a boolean"),
        ("is_sase_managed: [\n", "failed to parse YAML"),
        ("- not\n- a mapping\n", "expected a YAML mapping"),
    ],
)
def test_invalid_management_config_blocks_before_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
    expected_error: str,
) -> None:
    _mark_project(tmp_path, managed=False)
    (tmp_path / "sase.yml").write_text(config_text, encoding="utf-8")
    provider_calls: list[Path] = []
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda root: provider_calls.append(root) or "local",
    )

    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert any(expected_error in blocker for blocker in plan.blockers)
    assert provider_calls == []
    assert not (tmp_path / ".sase").exists()


def test_unmanaged_check_is_informative_and_successful(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_project(tmp_path, managed=False)

    assert run_sdd_init(_args(tmp_path, check=True)) == 0

    assert "not SASE-managed" in capsys.readouterr().out
    assert not (tmp_path / ".sase").exists()


def test_unmanaged_apply_skips_before_store_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_project(tmp_path, managed=False)
    calls: list[Path] = []
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda root, _workspace: calls.append(root),
    )

    assert run_sdd_init(_args(tmp_path)) == 0

    assert "not SASE-managed" in capsys.readouterr().out
    assert calls == []
    assert not (tmp_path / ".sase").exists()


def test_invalid_apply_fails_before_store_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_project(tmp_path, managed=False)
    (tmp_path / "sase.yml").write_text("is_sase_managed: wrong\n", encoding="utf-8")
    calls: list[Path] = []
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda root, _workspace: calls.append(root),
    )

    assert run_sdd_init(_args(tmp_path)) == 1

    assert "must be a boolean" in capsys.readouterr().err
    assert calls == []
    assert not (tmp_path / ".sase").exists()


def test_path_uses_target_repository_management_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    caller.mkdir()
    target.mkdir()
    _mark_project(caller)
    _mark_project(target, managed=False)
    monkeypatch.chdir(caller)
    provider_calls: list[Path] = []
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda root: provider_calls.append(root) or "local",
    )

    plan = plan_sdd_init(_args(target))

    assert plan.actions == ()
    assert "not SASE-managed" in plan.summary
    assert provider_calls == []


def test_run_uses_materialized_path_and_does_not_change_project_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    sdd_dir = tmp_path / ".sase" / "sdd"
    store = SddStore("separate_repo", sdd_dir, sdd_dir, "github", "remote")
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda _path, _workspace_num, **_options: store,
    )
    config_before = (tmp_path / "sase.yml").read_text(encoding="utf-8")

    assert run_sdd_init(_args(tmp_path)) == 0
    assert (sdd_dir / "README.md").is_file()
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == config_before


def test_init_registry_keeps_sdd_alias() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    assert specs["sdd"].plan is plan_sdd_init
    assert specs["sdd"].run is run_sdd_init
