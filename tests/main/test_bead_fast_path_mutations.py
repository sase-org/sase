"""Tests for bead CLI fast-path mutations and their side effects."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.main import bead_fast_path
from sase.main.bead_fast_path import (
    _mutation_commit_message,
    try_handle_bead_fast_path,
)


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

    assert (
        try_handle_bead_fast_path(
            [
                "create",
                "--title",
                "Second fast plan",
                "--type",
                f"plan({plan})",
                "--tier",
                "epic",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert try_handle_bead_fast_path(["rm", "plans-1", "plans-2"]) == 0
    output = capsys.readouterr().out
    assert "✗ Removed: plans-1 — Fast plan" in output
    assert "✗ Removed: plans-2 — Second fast plan" in output
    assert summaries[-1]["operation"] == "rm"
    assert summaries[-1]["issue_ids"] == ["plans-1", "plans-2"]


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
    assert _mutation_commit_message("rm", ["beads-1", "beads-2"]) == (
        "chore(beads): remove beads-1 beads-2"
    )
    assert _mutation_commit_message("dep_add", ["beads-1", "beads-2"]) == (
        "chore(beads): link beads-1 -> beads-2"
    )
    assert (
        _mutation_commit_message("dep_rm", ["beads-1", "beads-2", "beads-3"])
        == "chore(beads): unlink beads-1 -> beads-2 beads-3"
    )


def test_unchanged_fast_path_mutation_skips_auto_commit(
    tmp_path: Path, monkeypatch
) -> None:
    auto_commit = MagicMock()
    monkeypatch.setattr(
        "sase.bead.cli_common.auto_commit_bead_store",
        auto_commit,
    )

    bead_fast_path._apply_mutation_side_effects(
        tmp_path,
        {
            "operation": "update",
            "changed": False,
            "issue_ids": ["beads-1"],
        },
    )

    auto_commit.assert_not_called()


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
