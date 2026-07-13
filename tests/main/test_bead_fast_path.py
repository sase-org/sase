"""Tests for the lightweight bead CLI context resolver."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from sase.main import bead_fast_path
from sase.main.bead_fast_path import (
    _BEADS_DIRNAME,
    _BEADS_DIRNAME_NON_VC,
    _mutation_commit_message,
    _resolve_fast_path_context,
    _resolve_lightweight_beads_context,
    try_handle_bead_fast_path,
)


def _set_sdd_policy(monkeypatch, storage: str) -> None:
    vcs_name = {
        "in_tree": "bare_git",
        "separate_repo": "github",
    }.get(storage)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: vcs_name)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda _name: storage if storage != "local" else None,
    )


def test_lightweight_context_reads_current_checkout_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / "sdd/beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "in_tree")

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_prefers_current_vc_store_over_primary_non_vc(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "in_tree")

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_uses_primary_vc_store_over_primary_non_vc_in_vc_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    sibling.mkdir(parents=True)
    (primary / "sdd/beads").mkdir(parents=True)
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "in_tree")

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / "sdd/beads"]
    assert write_dir == primary / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_lightweight_context_uses_primary_non_vc_store_over_current_vc_in_non_vc_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "local")

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [primary / ".sase" / "sdd" / "beads"]
    assert write_dir == primary / ".sase" / "sdd" / "beads"
    assert beads_dirname == _BEADS_DIRNAME_NON_VC


def test_lightweight_context_uses_workspace_local_store_in_separate_repo_mode(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / ".sase" / "sdd" / "beads").mkdir(parents=True)
    nested = sibling / "src" / "pkg"
    nested.mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "separate_repo")

    result = _resolve_lightweight_beads_context(nested.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / ".sase" / "sdd" / "beads"]
    assert write_dir == sibling / ".sase" / "sdd" / "beads"
    assert beads_dirname == _BEADS_DIRNAME_NON_VC


def test_lightweight_context_treats_bare_git_as_in_tree(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    sibling = tmp_path / "workspaces" / "sase_106"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (sibling / "sdd/beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "bare_git")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: "in_tree" if vcs_name == "bare_git" else None,
    )

    result = _resolve_lightweight_beads_context(sibling.resolve())

    assert result is not None
    read_dirs, write_dir, beads_dirname = result
    assert read_dirs == [sibling / "sdd/beads"]
    assert write_dir == sibling / "sdd/beads"
    assert beads_dirname == _BEADS_DIRNAME


def test_fast_path_ignores_legacy_store_by_default(tmp_path: Path, monkeypatch) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase_beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "local")
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is None


def test_fast_path_routes_write_commands_for_non_vc_store(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "workspaces" / "sase"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _write_project_file(tmp_path, "sase", primary)
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_policy(monkeypatch, "local")
    monkeypatch.chdir(primary)

    context = _resolve_fast_path_context(["update", "sase-1", "--status", "closed"])

    assert context is not None
    assert context.write_beads_dir == primary / ".sase" / "sdd" / "beads"
    assert _resolve_fast_path_context(["create", "--title", "Created"]) is not None


def test_fast_path_routes_search_through_rust_executor(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    read_dir = tmp_path / "sdd/beads"
    read_dir.mkdir(parents=True)
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[read_dir],
        write_beads_dir=read_dir,
        relativize_design_paths=True,
    )
    calls: list[dict[str, Any]] = []

    def fake_binding(
        argv: list[str],
        read_beads_dirs: list[str],
        write_beads_dir: str,
        cwd: str,
        relativize_design_paths: bool,
    ) -> dict[str, object]:
        calls.append(
            {
                "argv": argv,
                "read_beads_dirs": read_beads_dirs,
                "write_beads_dir": write_beads_dir,
                "cwd": cwd,
                "relativize_design_paths": relativize_design_paths,
            }
        )
        return {"handled": True, "stdout": "rust search\n", "exit_code": 0}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda argv: context,
    )
    monkeypatch.setattr(
        "sase.core.rust.require_rust_binding",
        lambda name: fake_binding,
    )

    assert try_handle_bead_fast_path(["search", "needle"]) == 0

    assert capsys.readouterr().out == "rust search\n"
    assert calls == [
        {
            "argv": ["search", "needle"],
            "read_beads_dirs": [str(read_dir)],
            "write_beads_dir": str(read_dir),
            "cwd": str(tmp_path),
            "relativize_design_paths": True,
        }
    ]


def test_fast_path_defers_list_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for list: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["list"]) is None
    assert try_handle_bead_fast_path(["list", "--status", "closed"]) is None


def test_fast_path_defers_show_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for show: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["show", "beads-1.1"]) is None


def test_fast_path_defers_full_search_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for full search: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["search", "needle", "--format", "full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "--format=full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "-f", "full"]) is None
    assert try_handle_bead_fast_path(["search", "needle", "-ffull"]) is None


def test_fast_path_defers_search_help_to_argparse(monkeypatch) -> None:
    def fail_context(argv: list[str]):
        raise AssertionError(f"context should not resolve for help: {argv}")

    monkeypatch.setattr(bead_fast_path, "_resolve_fast_path_context", fail_context)

    assert try_handle_bead_fast_path(["search", "--help"]) is None


def test_fast_path_create_and_rm_use_rust_on_sidecar_layout(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from sase.bead.project import BeadProject

    root = tmp_path / "plans"
    with BeadProject.init(root, beads_dirname="beads"):
        pass
    plan = tmp_path / "plan.md"
    plan.write_text("# Fast path\n", encoding="utf-8")
    context = bead_fast_path._FastPathContext(
        read_beads_dirs=[root / "beads"],
        write_beads_dir=root / "beads",
        relativize_design_paths=False,
    )
    summaries: list[dict[str, Any]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        bead_fast_path,
        "_resolve_fast_path_context",
        lambda _argv: context,
    )
    monkeypatch.setattr(
        bead_fast_path,
        "_apply_mutation_side_effects",
        lambda _beads_dir, summary: summaries.append(summary),
    )
    monkeypatch.setattr(
        "sase.bead.sync.schedule_current_bead_refresh",
        lambda: None,
    )

    assert (
        try_handle_bead_fast_path(
            [
                "create",
                "--title",
                "Fast plan",
                "--type",
                f"plan({plan})",
                "--tier",
                "epic",
            ]
        )
        == 0
    )
    assert "Created plan: plans-1 — Fast plan" in capsys.readouterr().out
    assert summaries[-1]["operation"] == "create"
    from sase.bead.cli_common import storage_plan_path

    with BeadProject(root, beads_dirname="beads") as project:
        assert project.show("plans-1").design == storage_plan_path(plan.resolve())

    assert try_handle_bead_fast_path(["rm", "plans-1"]) == 0
    assert "✗ Removed: plans-1 — Fast plan" in capsys.readouterr().out
    assert summaries[-1]["operation"] == "rm"


def test_mutation_commit_messages_match_slow_path_contract() -> None:
    assert _mutation_commit_message("create", ["beads-1"]) == (
        "chore(beads): create beads-1"
    )
    assert _mutation_commit_message("update", ["beads-1"]) == (
        "chore(beads): update beads-1"
    )
    assert _mutation_commit_message("open", ["beads-1"]) == (
        "chore(beads): reopen beads-1"
    )
    assert _mutation_commit_message("close", ["beads-1", "beads-2"]) == (
        "chore(beads): close beads-1 beads-2"
    )
    assert _mutation_commit_message("rm", ["beads-1"]) == (
        "chore(beads): remove beads-1"
    )
    assert _mutation_commit_message("dep_add", ["beads-1", "beads-2"]) == (
        "chore(beads): link beads-1 -> beads-2"
    )


def test_warm_sidecar_fast_mutation_commits_without_network_git(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject
    from sase.sdd import _commit_store
    from sase.sdd.store import write_sdd_store_record

    primary = tmp_path / "project"
    workspace = tmp_path / "project_2"
    primary.mkdir()
    workspace.mkdir()
    marker_dir = workspace / ".sase"
    marker_dir.mkdir()
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "project_name": "project",
                "project_key": "project",
                "workspace_num": 2,
                "primary_workspace_dir": str(primary),
                "registry_path": str(primary / ".sase/registry.json"),
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )
    plans = workspace / "sase/repos/plans"
    plans.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=plans, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=plans, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=plans,
        check=True,
    )
    with BeadProject.init(plans, beads_dirname="beads") as project:
        issue = project.create("Warm mutation", IssueType.PLAN)
    (plans / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=plans, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"], cwd=plans, check=True, capture_output=True
    )

    git_ops: list[str] = []
    original_run_git = _commit_store.run_sdd_git

    def recording_run_git(*args, **kwargs):
        git_ops.append(str(kwargs.get("op")))
        return original_run_git(*args, **kwargs)

    monkeypatch.setattr(_commit_store, "run_sdd_git", recording_run_git)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "sdd": {
                "push_after_commit": False,
                "bead_refresh": {"mode": "off", "ttl_seconds": 120},
            }
        },
    )
    monkeypatch.chdir(workspace)

    assert (
        try_handle_bead_fast_path(["update", issue.id, "--status", "in_progress"]) == 0
    )

    assert "✓ Updated issue:" in capsys.readouterr().out
    assert git_ops
    assert not any(
        token in operation
        for operation in git_ops
        for token in ("fetch", "pull", "push", "clone")
    )
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=plans,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert subject == f"chore(beads): update {issue.id}"


def _write_project_file(home: Path, project_name: str, primary: Path) -> None:
    project_dir = home / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {primary}\n",
        encoding="utf-8",
    )
