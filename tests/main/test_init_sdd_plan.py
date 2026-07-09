"""Tests for the SDD ``sase init`` planner."""

from __future__ import annotations

import argparse
import subprocess
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
from sase.sdd.store import SddInitOutcome, SddMaterializationError, SddStore
from sase.sdd.store import _write_sdd_store_record


def _args(path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"path": str(path)}
    values.update(overrides)
    return argparse.Namespace(**values)


def _write_enabled_config(path: Path) -> None:
    (path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )


def _write_storage_config(path: Path, storage: str) -> None:
    (path / "sase.yml").write_text(
        f"sdd:\n  storage: {storage}\n",
        encoding="utf-8",
    )


def _mark_project(path: Path) -> None:
    (path / ".git").mkdir()


def _separate_repo_outcome(path: Path, *, created: bool = False) -> SddInitOutcome:
    sdd_dir = path / ".sase" / "sdd"
    return SddInitOutcome(
        store=SddStore(
            storage="separate_repo",
            sdd_dir=sdd_dir,
            repo_root=sdd_dir,
            provider="github",
            remote_url="git@github.com:acme/widget--sdd.git",
        ),
        repo="acme/widget--sdd",
        remote_url="git@github.com:acme/widget--sdd.git",
        created=created,
    )


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


def test_sdd_run_explicit_separate_repo_invokes_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    calls: list[tuple[Path, int]] = []

    def fake_create(path: Path, workspace_num: int) -> SddInitOutcome:
        calls.append((path, workspace_num))
        return _separate_repo_outcome(path)

    monkeypatch.setattr(
        "sase.sdd.store.create_and_materialize_sdd_store",
        fake_create,
    )

    assert run_sdd_init(_args(tmp_path, storage="separate_repo")) == 0
    assert calls == [(tmp_path, 1)]
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: separate_repo\n"
    )
    assert (tmp_path / ".sase" / "sdd" / "README.md").exists()
    assert not (tmp_path / "sdd" / "README.md").exists()


def test_sdd_run_github_policy_default_creates_separate_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    calls: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda project_root: "separate_repo",
    )

    def fake_create(path: Path, workspace_num: int) -> SddInitOutcome:
        calls.append((path, workspace_num))
        return _separate_repo_outcome(path, created=True)

    monkeypatch.setattr(
        "sase.sdd.store.create_and_materialize_sdd_store",
        fake_create,
    )

    assert run_sdd_init(_args(tmp_path)) == 0

    assert calls == [(tmp_path, 1)]
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: separate_repo\n"
    )
    assert (tmp_path / ".sase" / "sdd" / "README.md").exists()
    assert not (tmp_path / "sdd" / "README.md").exists()


def test_sdd_run_separate_repo_migrates_existing_in_tree_sdd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    _write_enabled_config(tmp_path)
    source = tmp_path / "sdd" / "research"
    source.mkdir(parents=True)
    (source / "note.md").write_text("notes\n", encoding="utf-8")
    local = tmp_path / ".sase" / "sdd" / "research"
    local.mkdir(parents=True)
    (local / "local-only.md").write_text("local\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda project_root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"version_controlled": True}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.create_sdd_remote",
        lambda *_args, **_kwargs: {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget--sdd",
            "remote_url": "git@github.com:acme/widget--sdd.git",
            "discovery": "found",
        },
    )

    def fake_run_git(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            1 if args == ["config", "--get", "remote.origin.url"] else 0,
            "",
            "",
        )

    monkeypatch.setattr("sase.sdd.migrate.run_sdd_git", fake_run_git)
    monkeypatch.setattr("sase.sdd.migrate._push_with_upstream", lambda _repo: True)
    monkeypatch.setattr(
        "sase.sdd.migrate._ensure_bead_store_initialized", lambda _sdd_dir: []
    )
    monkeypatch.setattr(
        "sase.sdd._commit.commit_sdd_store_files",
        lambda *_args, **_kwargs: True,
    )

    assert run_sdd_init(_args(tmp_path)) == 0

    migrated = tmp_path / ".sase" / "sdd" / "research"
    assert (migrated / "note.md").read_text(encoding="utf-8") == "notes\n"
    assert (migrated / "local-only.md").read_text(encoding="utf-8") == "local\n"
    assert (tmp_path / "sdd" / "research" / "note.md").exists()
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: separate_repo\n"
    )


def test_sdd_run_bare_git_policy_keeps_legacy_in_tree_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda project_root: "in_tree",
    )

    assert run_sdd_init(_args(tmp_path)) == 0

    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  version_controlled: true\n"
    )
    assert (tmp_path / "sdd" / "README.md").exists()
    assert not (tmp_path / ".sase" / "sdd" / "README.md").exists()


def test_sdd_run_separate_repo_failure_does_not_write_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_project(tmp_path)

    def fail_create(path: Path, workspace_num: int) -> SddInitOutcome:
        del path, workspace_num
        raise SddMaterializationError("GitHub CLI is not authenticated")

    monkeypatch.setattr(
        "sase.sdd.store.create_and_materialize_sdd_store",
        fail_create,
    )

    assert run_sdd_init(_args(tmp_path, storage="separate_repo")) == 1

    assert not (tmp_path / "sase.yml").exists()
    assert not (tmp_path / ".sase" / "sdd" / "README.md").exists()
    assert "GitHub CLI is not authenticated" in capsys.readouterr().err


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


def test_sdd_plan_existing_separate_repo_config_checks_dot_sase_sdd(
    tmp_path: Path,
) -> None:
    _mark_project(tmp_path)
    _write_storage_config(tmp_path, "separate_repo")
    _write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "acme/widget--sdd",
            "remote_url": "git@github.com:acme/widget--sdd.git",
            "discovery": "found",
        },
    )
    sdd_root = tmp_path / ".sase" / "sdd"
    write_sdd_readme(str(sdd_root))
    leftover = tmp_path / "sdd" / "research"
    leftover.mkdir(parents=True)
    (leftover / "note.md").write_text("leftover\n", encoding="utf-8")

    plan = plan_sdd_init(_args(tmp_path))

    assert plan.actions == ()
    assert plan.has_changes is False
    assert "current" in plan.summary


def test_sdd_plan_github_policy_reports_companion_repo_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda project_root: "separate_repo",
    )

    plan = plan_sdd_init(_args(tmp_path))

    assert any("companion" in action.detail for action in plan.actions)
    assert any(
        action.detail == "set sdd.storage to separate_repo" for action in plan.actions
    )
    assert any(
        action.path.is_relative_to(tmp_path / ".sase" / "sdd")
        for action in plan.actions
    )
    assert "companion SDD repository" in plan.summary


def test_sdd_plan_stale_negative_store_record_uses_generic_companion_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.sdd_handler._project_provider_sdd_policy",
        lambda project_root: "separate_repo",
    )
    _write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "acme/sdd",
            "remote_url": "git@github.com:acme/sdd.git",
            "discovery": "not_found",
        },
    )

    plan = plan_sdd_init(_args(tmp_path))

    details = [action.detail for action in plan.actions]
    assert any("companion SDD repository" in detail for detail in details)
    assert all("acme/sdd" not in detail for detail in details)


def test_sdd_init_registry_includes_sdd_planner() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}

    assert "sdd" in specs
    assert specs["sdd"].plan is plan_sdd_init
